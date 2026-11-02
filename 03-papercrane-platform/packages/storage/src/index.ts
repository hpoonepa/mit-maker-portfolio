export {
  createR2Client,
  resolveR2Config,
  r2Endpoint,
  type R2Config,
  type R2Handle,
} from "./client";

export {
  presignGet,
  presignPut,
  DEFAULT_PRESIGN_TTL_SEC,
} from "./presign";

export {
  uploadObject,
  multipartUpload,
  MULTIPART_THRESHOLD_BYTES,
  MULTIPART_PART_SIZE_BYTES,
  type UploadBody,
  type UploadOptions,
} from "./upload";

export {
  streamObject,
  type StreamObjectResult,
} from "./download";

export {
  deleteObject,
  deletePrefix,
  type DeletePrefixResult,
} from "./delete";

export {
  orgTargetKey,
  orgUploadStagingKey,
  jobDesignKey,
  jobLogKey,
  jobMetricsKey,
  jobPrefix,
  orgPrefix,
} from "./paths";

export { sha256Stream, sha256Tee } from "./checksum";
