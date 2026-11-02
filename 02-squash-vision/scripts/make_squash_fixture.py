from __future__ import annotations

import argparse
import subprocess
import sys
import shutil
from pathlib import Path

backend_root = Path(__file__).resolve().parents[1] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))
review_fixture_source = (
    Path(__file__).resolve().parents[1]
    / "tests/squashvision/fixtures/squash-review-real-model.mp4"
)

from squashvision.media import MediaError, resolve_ffmpeg_binary


def run_ffmpeg(
    arguments: list[str],
    *,
    ffmpeg_binary: Path,
    timeout_seconds: float = 60.0,
) -> None:
    try:
        subprocess.run(
            [str(ffmpeg_binary), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise RuntimeError("The bundled FFmpeg binary is unavailable") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("FFmpeg timed out while generating squash fixtures") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip()
        raise RuntimeError(f"FFmpeg fixture generation failed: {detail}") from error


def make_fixtures(
    output_dir: Path, ffmpeg_binary: Path | None = None
) -> tuple[Path, Path]:
    try:
        resolved_ffmpeg = ffmpeg_binary or resolve_ffmpeg_binary()
    except MediaError as error:
        raise RuntimeError(error.message) from error
    output_dir.mkdir(parents=True, exist_ok=True)
    cfr = output_dir / "squash_fixture.mp4"
    vfr = output_dir / "squash_fixture_vfr.mp4"

    court_filter = ",".join(
        [
            "drawbox=x=70:y=45:w=1140:h=630:color=white@0.9:t=5",
            "drawbox=x=70:y=250:w=1140:h=5:color=red@0.9:t=fill",
            "drawbox=x=640:y=45:w=5:h=630:color=white@0.7:t=fill",
            "drawbox=x='130+150*t':y='500-20*sin(2*PI*t)':w=55:h=125:color=0x42a5f5:t=fill",
            "drawbox=x='1050-145*t':y='475+25*sin(2*PI*t)':w=55:h=125:color=0xff7043:t=fill",
            "drawbox=x='620+300*sin(2*PI*t/1.25)':y='320+130*cos(2*PI*t/1.25)':w=13:h=13:color=white:t=fill",
        ]
    )
    run_ffmpeg(
        [
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x144b2f:s=1280x720:r=25:d=5",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.35*sin(2*PI*1800*t)*lt(mod(t\\,1)\\,0.025):s=48000:d=5",
            "-vf",
            court_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-metadata",
            "creation_time=2000-01-01T00:00:00Z",
            "-metadata:s:v:0",
            "rotate=0",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-threads",
            "1",
            "-shortest",
            "-y",
            str(cfr),
        ],
        ffmpeg_binary=resolved_ffmpeg,
        timeout_seconds=60,
    )
    run_ffmpeg(
        [
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(cfr),
            "-vf",
            "select='if(lt(t,2.5),not(mod(n,2)),1)'",
            "-fps_mode",
            "vfr",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-metadata",
            "creation_time=2000-01-01T00:00:00Z",
            "-metadata:s:v:0",
            "rotate=0",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-threads",
            "1",
            "-y",
            str(vfr),
        ],
        ffmpeg_binary=resolved_ffmpeg,
        timeout_seconds=60,
    )
    return cfr, vfr


def copy_review_fixture(output_dir: Path) -> Path:
    if not review_fixture_source.is_file():
        raise RuntimeError(
            "The deterministic real-model review fixture is unavailable"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "squash_review_fixture.mp4"
    shutil.copyfile(review_fixture_source, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic squash videos")
    parser.add_argument("output_dir", type=Path)
    arguments = parser.parse_args()
    try:
        cfr, vfr = make_fixtures(arguments.output_dir)
        review = copy_review_fixture(arguments.output_dir)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(cfr.name)
    print(vfr.name)
    print(review.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
