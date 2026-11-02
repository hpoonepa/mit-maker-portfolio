from __future__ import annotations

import math
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from itertools import combinations
from typing import Generic, TypeVar

import cv2
import numpy as np
from numpy.typing import NDArray

COURT_WIDTH_M = 6.40
COURT_LENGTH_M = 9.75
CALIBRATED_MEASUREMENT_THRESHOLD = 0.65
MAX_PLAYER_FLOOR_UNCERTAINTY_M = 0.75
_RANSAC_REPROJECTION_THRESHOLD_PX = 3.0
_MAX_NORMALIZED_CONDITION = 1.0e5
_MIN_FLOOR_COVERAGE = 0.005
_MIN_IMAGE_COVERAGE = 0.0005
# Confidence is heuristic: a tiny court must retain a resolution penalty even
# when it fills its own projected footprint. This pixel scale is independent
# of blank wall/letterbox area; it does not change the measurement threshold.
_FLOOR_RESOLUTION_REFERENCE_PX = 160.0


@dataclass(frozen=True, slots=True)
class Size:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("frame dimensions must be positive")


@dataclass(frozen=True, slots=True)
class ImagePoint:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class CourtPoint:
    x_m: float
    y_m: float


@dataclass(frozen=True, slots=True)
class CourtCorrespondence:
    label: str
    image: ImagePoint
    court: CourtPoint


@dataclass(frozen=True, slots=True)
class CourtKeypoints:
    points: tuple[CourtCorrespondence, ...]


class EvidenceLevel(StrEnum):
    UNAVAILABLE = "unavailable"
    ESTIMATED = "estimated"
    MEASURED = "measured"


class VisibleSurface(StrEnum):
    FLOOR = "floor"


@dataclass(frozen=True, slots=True)
class CalibrationCapabilities:
    image_space: bool
    floor_position: bool
    movement_distance: bool
    speed: bool


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    calibrated: bool
    image_to_court: tuple[tuple[float, float, float], ...] | None
    court_to_image: tuple[tuple[float, float, float], ...] | None
    residuals_px: tuple[float, ...]
    rms_error_px: float | None
    max_error_px: float | None
    inlier_mask: tuple[bool, ...]
    condition_number: float | None
    parameter_covariance: tuple[tuple[float, ...], ...] | None
    confidence: float
    capabilities: CalibrationCapabilities
    warnings: tuple[str, ...]

    def numeric_values(self) -> tuple[float, ...]:
        values: list[float] = []

        def visit(value: object) -> None:
            if isinstance(value, bool) or value is None:
                return
            if isinstance(value, (int, float, np.integer, np.floating)):
                values.append(float(value))
            elif is_dataclass(value):
                for field in fields(value):
                    visit(getattr(value, field.name))
            elif isinstance(value, (tuple, list)):
                for item in value:
                    visit(item)

        visit(self)
        return tuple(values)


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Estimate(Generic[T]):
    value: T | None
    covariance: tuple[tuple[float, float], tuple[float, float]]
    uncertainty: float | None
    inside_court: bool | None
    evidence: EvidenceLevel
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalibrationProposal:
    keypoints: CourtKeypoints
    confidence: float
    visible_surfaces: tuple[VisibleSurface, ...]
    warnings: tuple[str, ...]
    line_count: int
    intersection_count: int


def _matrix_tuple(matrix: NDArray[np.floating]) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in matrix)


def _polygon_area(points: NDArray[np.float64]) -> float:
    if len(points) < 3:
        return 0.0
    hull = cv2.convexHull(points.astype(np.float32))
    return float(abs(cv2.contourArea(hull)))


def _visible_floor_area(homography: NDArray[np.float64], frame_size: Size) -> float | None:
    """Area of the fitted floor inside the image, excluding unrelated walls.

    A denominator sign change puts a projective horizon inside the court, so
    such extrapolation must not improve calibration confidence. Clipping uses
    float64 arithmetic because rear corners can project beyond the image.
    """
    court = np.asarray(((0, 0, 1), (COURT_WIDTH_M, 0, 1),
                        (COURT_WIDTH_M, COURT_LENGTH_M, 1), (0, COURT_LENGTH_M, 1)), dtype=np.float64)
    projected = (homography @ court.T).T
    denominator = projected[:, 2]
    if (not np.isfinite(projected).all()
            or np.any(np.abs(denominator) <= 1.0e-9)
            or not (np.all(denominator > 0) or np.all(denominator < 0))):
        return None
    polygon = list(projected[:, :2] / denominator[:, None])
    for axis, bound, keep_greater in ((0, 0., True), (0, float(frame_size.width), False),
                                      (1, 0., True), (1, float(frame_size.height), False)):
        if not polygon:
            return None
        clipped = []
        previous = polygon[-1]
        previous_inside = previous[axis] >= bound if keep_greater else previous[axis] <= bound
        for current in polygon:
            current_inside = current[axis] >= bound if keep_greater else current[axis] <= bound
            if current_inside != previous_inside:
                fraction = (bound - previous[axis]) / (current[axis] - previous[axis])
                clipped.append(previous + fraction * (current - previous))
            if current_inside:
                clipped.append(current)
            previous, previous_inside = current, current_inside
        polygon = clipped
    if len(polygon) < 3:
        return None
    points = np.asarray(polygon, dtype=np.float64)
    area = abs(float(np.dot(points[:, 0], np.roll(points[:, 1], -1))
                     - np.dot(points[:, 1], np.roll(points[:, 0], -1)))) / 2
    return area if math.isfinite(area) and area > 1.0e-9 else None


def _has_near_duplicate(points: NDArray[np.float64], scale: float) -> bool:
    threshold = max(scale * 1.0e-6, 1.0e-9)
    return any(
        float(np.linalg.norm(points[left] - points[right])) <= threshold
        for left, right in combinations(range(len(points)), 2)
    )


def _normalize_points(
    points: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
    center = points.mean(axis=0)
    distances = np.linalg.norm(points - center, axis=1)
    mean_distance = float(distances.mean())
    if not math.isfinite(mean_distance) or mean_distance <= 1.0e-12:
        return None
    scale = math.sqrt(2.0) / mean_distance
    transform = np.array(
        [[scale, 0.0, -scale * center[0]], [0.0, scale, -scale * center[1]], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    homogeneous = np.column_stack((points, np.ones(len(points), dtype=np.float64)))
    normalized = (transform @ homogeneous.T).T[:, :2]
    return normalized, transform


def _dlt_condition(
    court_points: NDArray[np.float64], image_points: NDArray[np.float64]
) -> float | None:
    normalized_court = _normalize_points(court_points)
    normalized_image = _normalize_points(image_points)
    if normalized_court is None or normalized_image is None:
        return None
    source = normalized_court[0]
    target = normalized_image[0]
    rows: list[list[float]] = []
    for (x, y), (u, v) in zip(source, target, strict=True):
        rows.append([-x, -y, -1.0, 0.0, 0.0, 0.0, u * x, u * y, u])
        rows.append([0.0, 0.0, 0.0, -x, -y, -1.0, v * x, v * y, v])
    singular = np.linalg.svd(np.asarray(rows), compute_uv=False)
    denominator_index = -1 if len(rows) < 9 else -2
    denominator = float(singular[denominator_index])
    if denominator <= np.finfo(np.float64).eps:
        return None
    condition = float(singular[0] / denominator)
    return condition if math.isfinite(condition) else None


def _dlt_homography(
    court_points: NDArray[np.float64], image_points: NDArray[np.float64]
) -> NDArray[np.float64] | None:
    normalized_court = _normalize_points(court_points)
    normalized_image = _normalize_points(image_points)
    if normalized_court is None or normalized_image is None:
        return None
    source, source_transform = normalized_court
    target, target_transform = normalized_image
    rows: list[list[float]] = []
    for (x, y), (u, v) in zip(source, target, strict=True):
        rows.append([-x, -y, -1.0, 0.0, 0.0, 0.0, u * x, u * y, u])
        rows.append([0.0, 0.0, 0.0, -x, -y, -1.0, v * x, v * y, v])
    _, _, vectors = np.linalg.svd(np.asarray(rows, dtype=np.float64), full_matrices=True)
    normalized_homography = vectors[-1].reshape(3, 3)
    homography = (
        np.linalg.inv(target_transform)
        @ normalized_homography
        @ source_transform
    )
    if abs(float(homography[2, 2])) <= 1.0e-12:
        return None
    homography /= homography[2, 2]
    return homography if np.isfinite(homography).all() else None


def _parameter_covariance(
    court_points: NDArray[np.float64],
    image_points: NDArray[np.float64],
    homography: NDArray[np.float64],
    residuals: NDArray[np.float64],
) -> NDArray[np.float64] | None:
    rows: list[list[float]] = []
    for x_y in court_points:
        x, y = (float(x_y[0]), float(x_y[1]))
        denominator = homography[2, 0] * x + homography[2, 1] * y + 1.0
        if abs(denominator) <= 1.0e-12:
            return None
        numerator_u = homography[0, 0] * x + homography[0, 1] * y + homography[0, 2]
        numerator_v = homography[1, 0] * x + homography[1, 1] * y + homography[1, 2]
        u = numerator_u / denominator
        v = numerator_v / denominator
        rows.append([x / denominator, y / denominator, 1.0 / denominator, 0.0, 0.0, 0.0, -u * x / denominator, -u * y / denominator])
        rows.append([0.0, 0.0, 0.0, x / denominator, y / denominator, 1.0 / denominator, -v * x / denominator, -v * y / denominator])
    jacobian = np.asarray(rows, dtype=np.float64)
    degrees_of_freedom = max(1, 2 * len(court_points) - 8)
    variance = max(float(np.sum(np.square(residuals))) / degrees_of_freedom, 1.0e-12)
    covariance = variance * np.linalg.pinv(jacobian.T @ jacobian, rcond=1.0e-12)
    if covariance.shape != (8, 8) or not np.isfinite(covariance).all():
        return None
    return covariance


def _degraded(reason: str, point_count: int) -> CalibrationResult:
    return CalibrationResult(
        calibrated=False,
        image_to_court=None,
        court_to_image=None,
        residuals_px=(),
        rms_error_px=None,
        max_error_px=None,
        inlier_mask=tuple(False for _ in range(point_count)),
        condition_number=None,
        parameter_covariance=None,
        confidence=0.0,
        capabilities=CalibrationCapabilities(True, False, False, False),
        warnings=(reason,),
    )


def fit_calibration(keypoints: CourtKeypoints, frame_size: Size) -> CalibrationResult:
    if len(keypoints.points) < 4:
        return _degraded("insufficient_floor_correspondences", len(keypoints.points))
    image_points = np.asarray(
        [(point.image.x, point.image.y) for point in keypoints.points], dtype=np.float64
    )
    court_points = np.asarray(
        [(point.court.x_m, point.court.y_m) for point in keypoints.points], dtype=np.float64
    )
    if not np.isfinite(image_points).all() or not np.isfinite(court_points).all():
        return _degraded("non_finite_correspondence", len(keypoints.points))
    if (
        np.any(court_points[:, 0] < 0.0)
        or np.any(court_points[:, 0] > COURT_WIDTH_M)
        or np.any(court_points[:, 1] < 0.0)
        or np.any(court_points[:, 1] > COURT_LENGTH_M)
    ):
        return _degraded("court_point_out_of_bounds", len(keypoints.points))
    image_scale = math.hypot(frame_size.width, frame_size.height)
    court_scale = math.hypot(COURT_WIDTH_M, COURT_LENGTH_M)
    if _has_near_duplicate(image_points, image_scale) or _has_near_duplicate(court_points, court_scale):
        return _degraded("duplicate_correspondence", len(keypoints.points))
    candidate_floor_coverage = _polygon_area(court_points) / (
        COURT_WIDTH_M * COURT_LENGTH_M
    )
    candidate_image_coverage = _polygon_area(image_points) / (
        frame_size.width * frame_size.height
    )
    if (
        candidate_floor_coverage < _MIN_FLOOR_COVERAGE
        or candidate_image_coverage < _MIN_IMAGE_COVERAGE
    ):
        return _degraded("near_collinear_correspondences", len(keypoints.points))

    cv2.setRNGSeed(0)
    homography, mask = cv2.findHomography(
        court_points,
        image_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=_RANSAC_REPROJECTION_THRESHOLD_PX,
        maxIters=2000,
        confidence=0.995,
    )
    if homography is None or mask is None:
        return _degraded("homography_fit_failed", len(keypoints.points))
    inliers = mask.reshape(-1).astype(bool)
    if int(inliers.sum()) < 4:
        return _degraded("insufficient_ransac_inliers", len(keypoints.points))
    floor_coverage = _polygon_area(court_points[inliers]) / (
        COURT_WIDTH_M * COURT_LENGTH_M
    )
    image_coverage = _polygon_area(image_points[inliers]) / (
        frame_size.width * frame_size.height
    )
    if floor_coverage < _MIN_FLOOR_COVERAGE or image_coverage < _MIN_IMAGE_COVERAGE:
        return _degraded("near_collinear_ransac_inliers", len(keypoints.points))
    refit = _dlt_homography(court_points[inliers], image_points[inliers])
    if refit is None or abs(float(np.linalg.det(refit))) <= 1.0e-12:
        return _degraded("homography_refit_failed", len(keypoints.points))
    condition = _dlt_condition(court_points[inliers], image_points[inliers])
    if condition is None or condition > _MAX_NORMALIZED_CONDITION:
        return _degraded("ill_conditioned_homography", len(keypoints.points))
    visible_floor_area = _visible_floor_area(refit, frame_size)
    if visible_floor_area is None:
        return _degraded("invalid_projected_floor_footprint", len(keypoints.points))
    inverse = np.linalg.inv(refit)
    inverse /= inverse[2, 2]
    if not np.isfinite(inverse).all():
        return _degraded("non_finite_homography", len(keypoints.points))

    court_homogeneous = np.column_stack(
        (court_points, np.ones(len(court_points), dtype=np.float64))
    )
    projected_homogeneous = (refit @ court_homogeneous.T).T
    predicted = (
        projected_homogeneous[:, :2] / projected_homogeneous[:, 2, np.newaxis]
    )
    residuals = np.linalg.norm(predicted - image_points, axis=1)
    inlier_residuals = residuals[inliers]
    rms = float(math.sqrt(float(np.mean(np.square(inlier_residuals)))))
    maximum = float(np.max(inlier_residuals))
    covariance = _parameter_covariance(
        court_points[inliers], image_points[inliers], refit, inlier_residuals
    )
    if covariance is None:
        return _degraded("uncertainty_estimation_failed", len(keypoints.points))

    inlier_ratio = float(inliers.mean())
    residual_quality = math.exp(-rms / _RANSAC_REPROJECTION_THRESHOLD_PX)
    coverage_quality = math.sqrt(
        min(1.0, floor_coverage)
        * min(1.0, (_polygon_area(image_points[inliers]) / visible_floor_area) / 0.25)
    )
    coverage_quality *= min(1.0, math.sqrt(visible_floor_area) / _FLOOR_RESOLUTION_REFERENCE_PX)
    condition_quality = 1.0 / (1.0 + max(0.0, math.log10(condition)) / 6.0)
    confidence = float(
        np.clip(
            (
                0.35 * inlier_ratio
                + 0.25 * residual_quality
                + 0.25 * coverage_quality
                + 0.15 * condition_quality
            )
            * math.sqrt(coverage_quality),
            0.0,
            1.0,
        )
    )
    measurement = confidence >= CALIBRATED_MEASUREMENT_THRESHOLD
    warnings = () if measurement else ("low_calibration_confidence",)
    return CalibrationResult(
        calibrated=measurement,
        image_to_court=_matrix_tuple(inverse),
        court_to_image=_matrix_tuple(refit),
        residuals_px=tuple(float(value) for value in residuals),
        rms_error_px=rms,
        max_error_px=maximum,
        inlier_mask=tuple(bool(value) for value in inliers),
        condition_number=condition,
        parameter_covariance=_matrix_tuple(covariance),
        confidence=confidence,
        capabilities=CalibrationCapabilities(True, True, measurement, measurement),
        warnings=warnings,
    )


def _project_matrix(
    matrix: NDArray[np.float64], point: ImagePoint
) -> NDArray[np.float64] | None:
    homogeneous = matrix @ np.asarray([point.x, point.y, 1.0], dtype=np.float64)
    if abs(float(homogeneous[2])) <= 1.0e-12 or not np.isfinite(homogeneous).all():
        return None
    return homogeneous[:2] / homogeneous[2]


def _projection_covariance(
    point: ImagePoint,
    calibration: CalibrationResult,
    image_to_court: NDArray[np.float64],
    image_uncertainty_px: float | None,
) -> NDArray[np.float64]:
    denominator = (
        image_to_court[2, 0] * point.x
        + image_to_court[2, 1] * point.y
        + image_to_court[2, 2]
    )
    numerator_x = (
        image_to_court[0, 0] * point.x
        + image_to_court[0, 1] * point.y
        + image_to_court[0, 2]
    )
    numerator_y = (
        image_to_court[1, 0] * point.x
        + image_to_court[1, 1] * point.y
        + image_to_court[1, 2]
    )
    denominator_squared = denominator * denominator
    image_jacobian = np.asarray(
        [
            [
                (
                    image_to_court[0, 0] * denominator
                    - image_to_court[2, 0] * numerator_x
                )
                / denominator_squared,
                (
                    image_to_court[0, 1] * denominator
                    - image_to_court[2, 1] * numerator_x
                )
                / denominator_squared,
            ],
            [
                (
                    image_to_court[1, 0] * denominator
                    - image_to_court[2, 0] * numerator_y
                )
                / denominator_squared,
                (
                    image_to_court[1, 1] * denominator
                    - image_to_court[2, 1] * numerator_y
                )
                / denominator_squared,
            ],
        ],
        dtype=np.float64,
    )
    measurement_variance = (
        0.0
        if image_uncertainty_px is None
        else float(image_uncertainty_px) ** 2
    )
    pixel_variance = max(
        0.25,
        float(calibration.rms_error_px or 0.0) ** 2 + measurement_variance,
    )
    covariance = image_jacobian @ (np.eye(2) * pixel_variance) @ image_jacobian.T

    if (
        calibration.court_to_image is not None
        and calibration.parameter_covariance is not None
    ):
        court_to_image = np.asarray(calibration.court_to_image, dtype=np.float64)
        parameters = court_to_image.reshape(-1)[:8]
        parameter_jacobian = np.zeros((2, 8), dtype=np.float64)
        for index, parameter in enumerate(parameters):
            step = max(1.0e-7, abs(float(parameter)) * 1.0e-7)
            perturbed_values: list[NDArray[np.float64]] = []
            for direction in (-1.0, 1.0):
                varied = parameters.copy()
                varied[index] += direction * step
                varied_matrix = np.append(varied, 1.0).reshape(3, 3)
                try:
                    projected = _project_matrix(np.linalg.inv(varied_matrix), point)
                except np.linalg.LinAlgError:
                    projected = None
                if projected is None:
                    perturbed_values = []
                    break
                perturbed_values.append(projected)
            if len(perturbed_values) == 2:
                parameter_jacobian[:, index] = (
                    perturbed_values[1] - perturbed_values[0]
                ) / (2.0 * step)
        parameter_covariance = np.asarray(
            calibration.parameter_covariance, dtype=np.float64
        )
        covariance += (
            parameter_jacobian
            @ parameter_covariance
            @ parameter_jacobian.T
        )

    covariance = (covariance + covariance.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    eigenvalues = np.clip(eigenvalues, 1.0e-12, None)
    return eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T


def project_floor(
    point: ImagePoint,
    calibration: CalibrationResult,
    *,
    image_uncertainty_px: float | None = None,
) -> Estimate[CourtPoint]:
    if image_uncertainty_px is not None and (
        not math.isfinite(image_uncertainty_px)
        or image_uncertainty_px < 0
    ):
        raise ValueError("image uncertainty must be finite and nonnegative")
    if calibration.image_to_court is None:
        return Estimate(
            value=None,
            covariance=((0.0, 0.0), (0.0, 0.0)),
            uncertainty=None,
            inside_court=None,
            evidence=EvidenceLevel.UNAVAILABLE,
            warnings=("floor_projection_unavailable",),
        )
    matrix = np.asarray(calibration.image_to_court, dtype=np.float64)
    projected = _project_matrix(matrix, point)
    if projected is None:
        return Estimate(
            value=None,
            covariance=((0.0, 0.0), (0.0, 0.0)),
            uncertainty=None,
            inside_court=None,
            evidence=EvidenceLevel.UNAVAILABLE,
            warnings=("projection_singularity",),
        )
    x_m, y_m = (float(projected[0]), float(projected[1]))
    inside = 0.0 <= x_m <= COURT_WIDTH_M and 0.0 <= y_m <= COURT_LENGTH_M
    covariance_matrix = _projection_covariance(
        point,
        calibration,
        matrix,
        image_uncertainty_px,
    )
    uncertainty = float(math.sqrt(float(np.max(np.linalg.eigvalsh(covariance_matrix)))))
    covariance = (
        (float(covariance_matrix[0, 0]), float(covariance_matrix[0, 1])),
        (float(covariance_matrix[1, 0]), float(covariance_matrix[1, 1])),
    )
    warnings = list(calibration.warnings)
    if not inside:
        warnings.append("outside_court")
    evidence = (
        EvidenceLevel.MEASURED
        if calibration.confidence >= CALIBRATED_MEASUREMENT_THRESHOLD
        else EvidenceLevel.ESTIMATED
    )
    return Estimate(
        value=CourtPoint(x_m, y_m),
        covariance=covariance,
        uncertainty=uncertainty,
        inside_court=inside,
        evidence=evidence,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _line_angle(line: NDArray[np.int32]) -> float:
    x1, y1, x2, y2 = (float(value) for value in line)
    return math.atan2(y2 - y1, x2 - x1) % math.pi


def _line_intersection(
    first: NDArray[np.int32], second: NDArray[np.int32]
) -> tuple[float, float] | None:
    x1, y1, x2, y2 = (float(value) for value in first)
    x3, y3, x4, y4 = (float(value) for value in second)
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) <= 1.0e-9:
        return None
    cross_first = x1 * y2 - y1 * x2
    cross_second = x3 * y4 - y3 * x4
    x = (cross_first * (x3 - x4) - (x1 - x2) * cross_second) / denominator
    y = (cross_first * (y3 - y4) - (y1 - y2) * cross_second) / denominator
    return x, y


def _edge_support(edges: NDArray[np.uint8], start: tuple[float, float], end: tuple[float, float]) -> float:
    length = max(2, int(round(math.dist(start, end))))
    xs = np.linspace(start[0], end[0], length)
    ys = np.linspace(start[1], end[1], length)
    height, width = edges.shape
    supported = 0
    for x, y in zip(xs, ys, strict=True):
        xi = int(round(x))
        yi = int(round(y))
        left = max(0, xi - 2)
        right = min(width, xi + 3)
        top = max(0, yi - 2)
        bottom = min(height, yi + 3)
        if left < right and top < bottom and np.any(edges[top:bottom, left:right]):
            supported += 1
    return supported / length


def _has_internal_floor_topology(
    lines: list[NDArray[np.int32]],
    edges: NDArray[np.uint8],
    corners: tuple[tuple[float, float], ...],
) -> bool:
    image_corners = np.asarray(corners, dtype=np.float32)
    court_corners = np.asarray(
        [
            [0.0, 0.0],
            [COURT_WIDTH_M, 0.0],
            [COURT_WIDTH_M, COURT_LENGTH_M],
            [0.0, COURT_LENGTH_M],
        ],
        dtype=np.float32,
    )
    image_to_court = cv2.getPerspectiveTransform(image_corners, court_corners)
    transformed: list[
        tuple[NDArray[np.int32], tuple[float, float], tuple[float, float]]
    ] = []
    for line in lines:
        endpoints = np.asarray(
            [[[float(line[0]), float(line[1])], [float(line[2]), float(line[3])]]],
            dtype=np.float32,
        )
        court_endpoints = cv2.perspectiveTransform(endpoints, image_to_court)[0]
        if not np.isfinite(court_endpoints).all():
            continue
        transformed.append(
            (
                line,
                (float(court_endpoints[0, 0]), float(court_endpoints[0, 1])),
                (float(court_endpoints[1, 0]), float(court_endpoints[1, 1])),
            )
        )

    short_segments = [
        item
        for item in transformed
        if abs(item[1][1] - item[2][1]) <= 0.45
        and abs(item[1][0] - item[2][0]) >= 1.0
        and 3.0 <= (item[1][1] + item[2][1]) / 2.0 <= 7.5
        and _edge_support(
            edges,
            (float(item[0][0]), float(item[0][1])),
            (float(item[0][2]), float(item[0][3])),
        )
        >= 0.60
    ]
    half_lines = [
        item
        for item in transformed
        if abs(item[1][0] - item[2][0]) <= 0.55
        and abs(item[1][1] - item[2][1]) >= 2.5
        and 2.35 <= (item[1][0] + item[2][0]) / 2.0 <= 4.05
        and _edge_support(
            edges,
            (float(item[0][0]), float(item[0][1])),
            (float(item[0][2]), float(item[0][3])),
        )
        >= 0.60
    ]
    for anchor in short_segments:
        short_y = (anchor[1][1] + anchor[2][1]) / 2.0
        collinear = [
            item
            for item in short_segments
            if abs((item[1][1] + item[2][1]) / 2.0 - short_y) <= 0.45
        ]
        minimum_x = min(min(item[1][0], item[2][0]) for item in collinear)
        maximum_x = max(max(item[1][0], item[2][0]) for item in collinear)
        if minimum_x > 0.8 or maximum_x < COURT_WIDTH_M - 0.8:
            continue
        for half in half_lines:
            ordered_half = sorted((half[1], half[2]), key=lambda point: point[1])
            if (
                abs(ordered_half[0][1] - short_y) > 0.8
                or ordered_half[1][1] < 8.5
            ):
                continue
            delta_y = ordered_half[1][1] - ordered_half[0][1]
            if delta_y <= 1.0e-9:
                continue
            fraction = (short_y - ordered_half[0][1]) / delta_y
            intersection_x = (
                ordered_half[0][0]
                + fraction * (ordered_half[1][0] - ordered_half[0][0])
            )
            if abs(intersection_x - COURT_WIDTH_M / 2.0) <= 0.75:
                return True
    return False


def detect_court(frame: NDArray[np.uint8]) -> CalibrationProposal:
    if frame.ndim not in (2, 3) or frame.size == 0:
        return CalibrationProposal(CourtKeypoints(()), 0.0, (), ("invalid_frame",), 0, 0)
    if frame.ndim == 3 and frame.shape[2] not in (3, 4):
        return CalibrationProposal(CourtKeypoints(()), 0.0, (), ("invalid_frame",), 0, 0)
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY if frame.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    normalized = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    edges = cv2.Canny(normalized, 60, 180, apertureSize=3)
    height, width = edges.shape
    minimum_length = max(30, int(0.20 * min(width, height)))
    detected = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 360,
        threshold=max(30, int(0.06 * min(width, height))),
        minLineLength=minimum_length,
        maxLineGap=max(8, int(0.03 * min(width, height))),
    )
    if detected is None:
        return CalibrationProposal(CourtKeypoints(()), 0.0, (), ("insufficient_line_evidence",), 0, 0)
    lines = [line.astype(np.int32) for line in detected.reshape(-1, 4)]
    lines.sort(key=lambda line: (-math.dist((int(line[0]), int(line[1])), (int(line[2]), int(line[3]))), tuple(int(v) for v in line)))
    lines = lines[:24]
    horizontal = [line for line in lines if abs(math.sin(_line_angle(line))) <= 0.50]
    side = [line for line in lines if abs(math.sin(_line_angle(line))) > 0.50]
    intersections = [
        intersection
        for first, second in combinations(lines, 2)
        if abs(math.sin(_line_angle(first) - _line_angle(second))) > 0.25
        and (intersection := _line_intersection(first, second)) is not None
        and -0.25 * width <= intersection[0] <= 1.25 * width
        and -0.25 * height <= intersection[1] <= 1.25 * height
    ]
    if len(horizontal) < 2 or len(side) < 2:
        return CalibrationProposal(
            CourtKeypoints(()),
            min(0.25, 0.03 * len(lines)),
            (),
            ("insufficient_orientation_evidence",),
            len(lines),
            len(intersections),
        )

    best: tuple[float, tuple[tuple[float, float], ...]] | None = None
    for top, bottom in combinations(horizontal[:10], 2):
        top_y = (float(top[1]) + float(top[3])) / 2.0
        bottom_y = (float(bottom[1]) + float(bottom[3])) / 2.0
        if top_y > bottom_y:
            top, bottom = bottom, top
            top_y, bottom_y = bottom_y, top_y
        if bottom_y - top_y < 0.15 * height:
            continue
        for left, right in combinations(side[:12], 2):
            left_x = (float(left[0]) + float(left[2])) / 2.0
            right_x = (float(right[0]) + float(right[2])) / 2.0
            if left_x > right_x:
                left, right = right, left
            corners_raw = (
                _line_intersection(top, left),
                _line_intersection(top, right),
                _line_intersection(bottom, right),
                _line_intersection(bottom, left),
            )
            if any(corner is None for corner in corners_raw):
                continue
            corners = tuple(corner for corner in corners_raw if corner is not None)
            if any(not (-0.03 * width <= x <= 1.03 * width and -0.03 * height <= y <= 1.03 * height) for x, y in corners):
                continue
            contour = np.asarray(corners, dtype=np.float32)
            area_fraction = abs(float(cv2.contourArea(contour))) / (width * height)
            if area_fraction < 0.08 or not cv2.isContourConvex(contour):
                continue
            top_width = math.dist(corners[0], corners[1])
            bottom_width = math.dist(corners[3], corners[2])
            if min(top_width, bottom_width) < 0.15 * width or bottom_width < 0.75 * top_width:
                continue
            supports = tuple(
                _edge_support(edges, start, end)
                for start, end in zip(corners, corners[1:] + corners[:1], strict=True)
            )
            if min(supports) < 0.45:
                continue
            support = sum(supports) / 4.0
            perspective_quality = min(1.0, bottom_width / max(top_width, 1.0))
            score = 0.70 * support + 0.20 * min(1.0, area_fraction / 0.35) + 0.10 * perspective_quality
            candidate = (score, corners)
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is None:
        return CalibrationProposal(
            CourtKeypoints(()),
            min(0.35, 0.02 * len(lines) + 0.005 * min(len(intersections), 20)),
            (),
            ("no_coherent_court_quadrilateral",),
            len(lines),
            len(intersections),
        )

    score, corners = best
    confidence = float(np.clip(score, 0.0, 1.0))
    if confidence < CALIBRATED_MEASUREMENT_THRESHOLD:
        return CalibrationProposal(
            CourtKeypoints(()),
            confidence,
            (),
            ("weak_court_line_support",),
            len(lines),
            len(intersections),
        )
    if not _has_internal_floor_topology(lines, edges, corners):
        return CalibrationProposal(
            CourtKeypoints(()),
            min(confidence, 0.49),
            (),
            ("missing_internal_court_topology",),
            len(lines),
            len(intersections),
        )
    labels = ("front_left", "front_right", "back_right", "back_left")
    court_points = (
        CourtPoint(0.0, 0.0),
        CourtPoint(COURT_WIDTH_M, 0.0),
        CourtPoint(COURT_WIDTH_M, COURT_LENGTH_M),
        CourtPoint(0.0, COURT_LENGTH_M),
    )
    proposed = CourtKeypoints(
        tuple(
            CourtCorrespondence(label, ImagePoint(float(corner[0]), float(corner[1])), court)
            for label, corner, court in zip(labels, corners, court_points, strict=True)
        )
    )
    return CalibrationProposal(
        proposed,
        confidence,
        (VisibleSurface.FLOOR,),
        (),
        len(lines),
        len(intersections),
    )


__all__ = [
    "CALIBRATED_MEASUREMENT_THRESHOLD",
    "COURT_LENGTH_M",
    "COURT_WIDTH_M",
    "MAX_PLAYER_FLOOR_UNCERTAINTY_M",
    "CalibrationCapabilities",
    "CalibrationProposal",
    "CalibrationResult",
    "CourtCorrespondence",
    "CourtKeypoints",
    "CourtPoint",
    "Estimate",
    "EvidenceLevel",
    "ImagePoint",
    "VisibleSurface",
    "Size",
    "detect_court",
    "fit_calibration",
    "project_floor",
]
