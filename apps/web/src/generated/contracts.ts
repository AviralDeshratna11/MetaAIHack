/* Generated from Pydantic JSON Schema. Run python -m scripts.export_schemas && npm run schemas. */

export type Video2RobotContracts =
  | ActionGraph
  | ArtifactManifest
  | Correction
  | Entity
  | ErrorResponse
  | JobEvent
  | LayerOneHandoffManifest
  | ModelRun
  | ProcessRequest
  | Provenance
  | SemanticPlan
  | StageResult
  | TrackFrame
  | TrackSummary
  | UploadRequest
  | VideoAsset
  | VideoManifest
  | ArtifactsResponse
  | HealthResponse
  | JobDetail
  | JobView
  | TrackingReport
  | TracksResponse
  | UploadCompleteResponse
  | UploadResponse
  | VideoDetail
  | VideoListResponse
  | ReconstructionRequest
  | ReconstructionConfig
  | Pose3D
  | Alignment
  | CameraFrame
  | PoseFrame
  | RelativeFrame
  | ContactFrame
  | InteractionEvent
  | RefinedAction
  | AffordancePatch
  | ReconstructionReport
  | LayerTwoHandoff
  | GeometryWindow
  | InteractionTrajectory;
export type SchemaVersion = "0.1.0";
export type Nodes = string[];
export type SchemaVersion1 = "0.1.0";
export type Source = string;
export type Target = string;
export type Reason = "precondition" | "temporal" | "task_dependency";
export type Edges = Edge[];
export type SchemaVersion2 = "0.1.0";
export type ArtifactId = string;
export type Uri = string;
export type Sha256 = string;
export type ByteCount = number;
export type MediaType = string;
export type Stage = string;
export type RunId = string;
export type InputHashes = string[];
export type ConfigHash = string;
export type CodeHash = string;
export type Model = string | null;
export type ModelRevision = string | null;
export type PromptHash = string | null;
export type CreatedAt = string;
export type InferenceMode = "fixture" | "live";
export type SchemaVersion3 = "0.1.0";
export type SourceJobId = string;
export type EntityId = string;
export type ShotId = string;
export type FrameIndex = number;
export type Kind = "point" | "box" | "association";
export type Point = [number, number] | null;
export type BboxXyxy = [number, number, number, number] | null;
export type ProviderTrackId = string | null;
export type SchemaVersion4 = "0.1.0";
export type EntityId1 = string;
export type Category = string;
export type SemanticName = string;
export type SamPrompt = string;
export type Role = "actor" | "manipulated_object" | "target" | "support" | "other";
export type Motion = "manipulated" | "static" | "unknown";
export type Handedness = "left" | "right" | "unknown";
export type SchemaVersion5 = "0.1.0";
export type StartS = number;
export type EndS = number;
export type VisibilityIntervals = Interval[];
export type Confidence = number | null;
export type UncertaintyReasons = string[];
export type SchemaVersion6 = "0.1.0";
export type Code = string;
export type Message = string;
export type Retryable = boolean;
export type SchemaVersion7 = "0.1.0";
export type Sequence = number;
export type JobId = string;
export type Status = string;
export type Stage1 = string | null;
export type CreatedAt1 = string;
export type SchemaVersion8 = "0.1.0";
export type VideoId = string;
export type RunId1 = string;
export type InferenceMode1 = "fixture" | "live";
export type Entities = string[];
export type ReadyForGeometry = boolean;
export type ReviewReasons = string[];
export type MetricScaleValid = false;
export type Coordinates =
  "normalized-video pixels; x right, y down; half-open boxes; zero-based frames; seconds from normalized start";
export type Certification = "2d_perception_only";
export type SchemaVersion9 = "0.1.0";
export type ModelRunId = string;
export type Model1 = string;
export type Revision = string | null;
export type Stage2 = string;
export type InferenceMode2 = "fixture" | "live";
export type InputHash = string;
export type ConfigHash1 = string;
export type PromptHash1 = string;
export type Status1 = string;
export type RequestId = string | null;
export type LatencyMs = number | null;
export type ActualCostUsd = number | null;
export type EstimatedCostUsd = number | null;
export type Attempt = number;
export type Warnings = string[];
export type Error = {
  [k: string]: unknown;
} | null;
export type SchemaVersion10 = "0.1.0";
export type IdempotencyKey = string;
export type SchemaVersion11 = "0.1.0";
export type SourceUri = string | null;
export type RightsStatus = "team_recorded" | "licensed" | "user_supplied" | "synthetic" | "unknown";
export type License = string | null;
export type Consent = string | null;
export type Uploader = string | null;
export type SchemaVersion12 = "0.1.0";
export type Task = string;
export type CanonicalSkill = string;
export type DurationS = number;
/**
 * @minItems 1
 */
export type Entities1 = [Entity, ...Entity[]];
/**
 * @minItems 1
 */
export type Actions = [ActionSegment, ...ActionSegment[]];
export type SchemaVersion13 = "0.1.0";
export type StartS1 = number;
export type EndS1 = number;
export type ActionId = string;
export type Primitive =
  | "REACH"
  | "GRASP"
  | "LIFT"
  | "TRANSPORT"
  | "ROTATE"
  | "POUR"
  | "INSERT"
  | "PUSH"
  | "PULL"
  | "OPEN"
  | "CLOSE"
  | "PLACE"
  | "RELEASE"
  | "WIPE"
  | "PRESS"
  | "UNKNOWN";
export type Actor = string | null;
export type Object = string | null;
export type Target1 = string | null;
export type Part = string | null;
export type TimingSource = "semantic";
export type RequiresContact = boolean | null;
export type SchemaVersion14 = "0.1.0";
export type Relation = string;
export type EntityIds = string[];
export type Negated = boolean;
export type Preconditions = Predicate[];
export type Effects = Predicate[];
export type Confidence1 = number | null;
export type UncertaintyReasons1 = string[];
export type Warnings1 = string[];
export type SchemaVersion15 = "0.1.0";
export type Stage3 = string;
export type RunId2 = string;
export type Status2 = string;
export type ArtifactIds = string[];
export type Warnings2 = string[];
export type Error1 = {
  [k: string]: unknown;
} | null;
export type SchemaVersion16 = "0.1.0";
export type VideoId1 = string;
export type ShotId1 = string;
export type FrameIndex1 = number;
export type Timestamp = number;
export type SourceTimestamp = number;
export type EntityId2 = string;
export type TrackId = string;
export type ProviderTrackId1 = string | null;
export type MaskRef = string | null;
export type BboxXyxy1 = [number, number, number, number] | null;
export type Centroid = [number, number] | null;
export type CentroidNormalized = [number, number] | null;
export type ProviderConfidence = number | null;
export type TrackingConfidence = number | null;
export type Observed = boolean;
export type Visibility = "VISIBLE" | "PARTIALLY_OCCLUDED" | "FULLY_OCCLUDED" | "CANDIDATE_REAPPEARANCE" | "LOST";
export type Origin = "measured" | "interpolated" | "predicted" | "missing";
export type IdentityStatus = "associated" | "ambiguous" | "unverified" | "lost";
export type Warnings3 = string[];
export type ModelRunId1 = string;
export type SchemaVersion17 = "0.1.0";
export type EntityId3 = string;
export type TrackId1 = string;
export type ObservedFrameCoverage = number;
export type ExpectedVisibleFrameCoverage = number | null;
export type MissingFrames = number;
export type LongestMissingRun = number;
export type Reinitializations = number;
export type VerifiedIdSwitches = number | null;
export type AnomalyCount = number;
export type IdentityStatus1 = string;
export type SchemaVersion18 = "0.1.0";
export type Filename = string;
export type ByteCount1 = number;
export type Sha2561 = string;
export type SchemaVersion19 = "0.1.0";
export type VideoId2 = string;
export type OriginalRef = string;
export type SourceHash = string;
export type ByteCount2 = number;
export type SchemaVersion20 = "0.1.0";
export type VideoId3 = string;
export type NormalizedRef = string;
export type Width = number;
export type Height = number;
export type FpsNum = number;
export type FpsDen = number;
export type FrameCount = number;
export type DurationS1 = number;
export type PixelFormat = string;
export type NormalizationHash = string;
export type FrameMapRef = string;
export type SchemaVersion21 = "0.1.0";
export type ShotId2 = string;
export type StartFrame = number;
export type EndFrame = number;
export type Shots = Shot[];
export type KeyframeRefs = string[];
export type SchemaVersion22 = "0.1.0";
export type RunId3 = string;
export type InferenceMode3 = "fixture" | "live";
export type SchemaVersion23 = "0.1.0";
export type ArtifactId1 = string;
export type Uri1 = string;
export type Sha2562 = string;
export type ByteCount3 = number;
export type MediaType1 = string;
export type Stage4 = string;
export type RunId4 = string;
export type InputHashes1 = string[];
export type ConfigHash2 = string;
export type CodeHash1 = string;
export type Model2 = string | null;
export type ModelRevision1 = string | null;
export type PromptHash2 = string | null;
export type CreatedAt2 = string;
export type InferenceMode4 = "fixture" | "live";
export type Name = string;
export type Url = string;
export type Artifacts1 = ArtifactView[];
export type SchemaVersion24 = "0.1.0";
export type Status3 = "ok" | "ready";
export type InferenceMode5 = "fixture" | "live";
export type Scope = string | null;
export type SchemaVersion25 = "0.1.0";
export type JobId1 = string;
export type VideoId4 = string;
export type RunId5 = string;
export type Status4 = string;
export type Stage5 = string | null;
export type InferenceMode6 = "fixture" | "live";
export type Pipeline = "perception" | "reconstruction";
export type Error2 = {
  [k: string]: unknown;
} | null;
export type SourceJobId1 = string | null;
export type CreatedAt3 = string;
export type SchemaVersion26 = "0.1.0";
export type Stage6 = string;
export type Attempt1 = number;
export type Status5 = string;
export type Error3 = {
  [k: string]: unknown;
} | null;
export type Stages = StageView[];
export type SchemaVersion27 = "0.1.0";
export type ModelRunId2 = string;
export type Model3 = string;
export type Revision1 = string | null;
export type Stage7 = string;
export type InferenceMode7 = "fixture" | "live";
export type InputHash1 = string;
export type ConfigHash3 = string;
export type PromptHash3 = string;
export type Status6 = string;
export type RequestId1 = string | null;
export type LatencyMs1 = number | null;
export type ActualCostUsd1 = number | null;
export type EstimatedCostUsd1 = number | null;
export type Attempt2 = number;
export type Warnings4 = string[];
export type Error4 = {
  [k: string]: unknown;
} | null;
export type RawRef = string | null;
export type ModelRuns = ModelRunView[];
export type SchemaVersion28 = "0.1.0";
export type JobId2 = string;
export type VideoId5 = string;
export type RunId6 = string;
export type Status7 = string;
export type Stage8 = string | null;
export type InferenceMode8 = "fixture" | "live";
export type Pipeline1 = "perception" | "reconstruction";
export type Error5 = {
  [k: string]: unknown;
} | null;
export type SourceJobId2 = string | null;
export type CreatedAt4 = string;
export type SchemaVersion29 = "0.1.0";
export type InferenceMode9 = "fixture" | "live";
export type Calibration = string;
export type Summaries = TrackSummary[];
export type SchemaVersion30 = "0.1.0";
export type EntityId4 = string;
export type ShotId3 = string;
export type FrameIndex2 = number;
export type MaskRef1 = string;
export type Method = string;
export type Anchors = Anchor[];
export type ReviewReasons1 = string[];
export type MaskBundles = string[];
export type Reprojection = "not_evaluated";
export type PhysicalFeasibility = "not_evaluated";
export type SchemaVersion31 = "0.1.0";
export type Total = number;
export type Offset = number;
export type Tracks = TrackFrame[];
export type SchemaVersion32 = "0.1.0";
export type Encoding = "row-major-rle-v1";
export type Height1 = number;
export type Width1 = number;
export type Counts = number[];
export type SchemaVersion33 = "0.1.0";
export type VideoId6 = string;
export type Status8 = string;
export type Probe = {
  [k: string]: unknown;
} | null;
export type SchemaVersion34 = "0.1.0";
export type VideoId7 = string;
export type UploadUrl = string;
export type ExpiresIn = number;
export type InferenceMode10 = "fixture" | "live";
export type SchemaVersion35 = "0.1.0";
export type VideoId8 = string;
export type Filename1 = string;
export type Status9 = string;
export type Probe1 = {
  [k: string]: unknown;
} | null;
export type Jobs = JobView[];
export type SourceUrl = string | null;
export type SchemaVersion36 = "0.1.0";
export type SchemaVersion37 = "0.1.0";
export type VideoId9 = string;
export type Filename2 = string;
export type Status10 = string;
export type Videos = VideoListItem[];
export type SchemaVersion38 = "0.2.0";
export type SourceJobId3 = string;
export type IdempotencyKey1 = string;
export type SchemaVersion39 = "0.2.0";
export type Backend = "fixture" | "vggt";
export type BodyBackend = "none" | "sam3d";
export type SampleFps = number;
export type MaxFramesPerShot = number;
export type MaxTotalFrames = number;
export type MaxPointsPerEntity = number;
export type ContactDistance2DPx = number;
export type ContactDistance3DRelative = number;
export type ContactOn = number;
export type ContactOff = number;
export type PersistenceFrames = number;
export type BoundaryWindowS = number;
export type MaxAlignmentRelativeRmse = number;
export type AllowReviewSource = boolean;
export type SchemaVersion40 = "0.2.0";
/**
 * @minItems 3
 * @maxItems 3
 */
export type PositionXyz = [number, number, number];
export type QuaternionXyzw = [number, number, number, number] | null;
export type Confidence2 = number | null;
export type MetricScaleValid1 = false;
export type SchemaVersion41 = "0.2.0";
export type AlignmentId = string;
export type SourceFrame = string;
export type TargetFrame = string;
export type Rotation = [number, number, number][];
/**
 * @minItems 3
 * @maxItems 3
 */
export type Translation = [number, number, number];
export type Scale = number;
export type Rmse = number;
export type CorrespondenceCount = number;
export type Method1 = string;
export type Uncertainty = string;
export type SchemaVersion42 = "0.2.0";
export type VideoId10 = string;
export type ShotId4 = string;
export type FrameIndex3 = number;
export type Timestamp1 = number;
export type WorldFrame = string;
export type Intrinsic = [number, number, number][];
export type WorldFromCamera = [number, number, number, number][];
export type ImageWidth = number;
export type ImageHeight = number;
export type Source1 = string;
export type Origin1 = "estimated" | "synthetic";
export type MetricScaleValid2 = false;
export type SchemaVersion43 = "0.2.0";
export type VideoId11 = string;
export type ShotId5 = string;
export type FrameIndex4 = number;
export type Timestamp2 = number;
export type EntityId5 = string;
export type TrackId2 = string;
export type WorldFrame1 = string;
export type PointsWorld = [number, number, number][];
export type KeypointNames = string[];
export type KeypointsWorld = [number, number, number][];
export type LinearVelocity = [number, number, number] | null;
export type AngularVelocity = [number, number, number] | null;
export type ProjectedCentroid = [number, number] | null;
export type ReprojectionErrorPx = number | null;
export type Origin2 = "estimated" | "synthetic" | "missing";
export type Representation = "surface_centroid" | "wrist" | "point_tracks" | "missing";
export type OrientationStatus = "unknown" | "pca_hypothesis" | "synthetic";
export type Source2 = string;
export type AlignmentId1 = string | null;
export type Warnings5 = string[];
export type SchemaVersion44 = "0.2.0";
export type ShotId6 = string;
export type FrameIndex5 = number;
export type Timestamp3 = number;
export type WorldFrame2 = string;
export type HandId = string;
export type ObjectId = string;
export type HandTrackId = string;
export type ObjectTrackId = string;
export type RelativePositionWorldXyz = [number, number, number] | null;
export type Origin3 = "estimated" | "synthetic" | "missing";
export type Warnings6 = string[];
export type SchemaVersion45 = "0.2.0";
export type ShotId7 = string;
export type FrameIndex6 = number;
export type Timestamp4 = number;
export type HandId1 = string;
export type ObjectId1 = string;
export type HandTrackId1 = string | null;
export type ObjectTrackId1 = string | null;
export type State = "CONTACT" | "NO_CONTACT" | "CANDIDATE" | "UNKNOWN";
export type Probability = number | null;
export type ProbabilityCalibrated = false;
export type Distance2DPx = number | null;
export type Distance3DRelative = number | null;
export type GeometryAgeS = number | null;
export type GeometryOrigin = "sampled" | "held" | "missing";
export type MotionCoupling = number | null;
export type SemanticPrior = number | null;
export type ContactPointsObject = [number, number, number][];
export type EvidenceOrigin = "estimated" | "synthetic" | "missing";
export type Warnings7 = string[];
export type SchemaVersion46 = "0.2.0";
export type EventId = string;
export type ShotId8 = string;
export type FrameIndex7 = number;
export type Timestamp5 = number;
export type HandId2 = string;
export type ObjectId2 = string;
export type Kind1 = "contact_on" | "contact_off" | "grasp_candidate" | "release_candidate";
export type Confidence3 = number | null;
export type ValidatedGrasp = false;
export type Reasons = string[];
export type SchemaVersion47 = "0.2.0";
export type ActionId1 = string;
export type SemanticStartS = number;
export type SemanticEndS = number;
export type RefinedStartS = number | null;
export type RefinedEndS = number | null;
export type TimingSource1 = "semantic" | "contact_candidate";
export type EvidenceEventIds = string[];
export type ReviewReasons2 = string[];
export type SchemaVersion48 = "0.2.0";
export type ObjectId3 = string;
export type HandId3 = string;
export type ShotId9 = string;
export type FrameIndex8 = number;
export type Primitive1 = "contact";
export type PartName = string | null;
export type ContactPatchObjectXyz = [number, number, number][];
export type ApproachDirection = [number, number, number] | null;
export type ObservedGrasp = false;
export type Source3 = "estimated_surface_proximity" | "synthetic";
export type SchemaVersion49 = "0.2.0";
export type SourceRunId = string;
export type Backend1 = string;
export type InferenceMode11 = "fixture" | "live";
export type ScaleMode = "relative";
export type MetricScaleValid3 = false;
export type WorldFrames = string[];
export type SampledFrames = number[];
export type CameraFrames = number;
export type HandPoseFrames = number;
export type ObjectPoseFrames = number;
export type RelativePoseFrames = number;
export type ContactFrames = number;
export type ContactEvents = number;
export type ReprojectionMedianPx = number | null;
export type ReprojectionMetric = string;
export type ReviewReasons3 = string[];
export type PhysicalFeasibility1 = "not_evaluated";
export type SchemaVersion50 = "0.2.0";
export type VideoId12 = string;
export type RunId7 = string;
export type SourceRunId1 = string;
export type InferenceMode12 = "fixture" | "live";
export type ReadyForRobotization = boolean;
export type MetricScaleValid4 = false;
export type ScaleMode1 = "relative";
export type Certification1 = "interaction_hypotheses_only";
export type ReviewReasons4 = string[];
export type Coordinates1 = string;
export type SchemaVersion51 = "0.2.0";
export type Total1 = number;
export type Offset1 = number;
export type Cameras = CameraFrame[];
export type Hands = PoseFrame[];
export type Objects = PoseFrame[];
export type Relative = RelativeFrame[];
export type Contacts = ContactFrame[];
export type SchemaVersion52 = "0.2.0";
export type VideoId13 = string;
export type RunId8 = string;
export type SourceRunId2 = string;
export type Task1 = string;
export type CanonicalSkill1 = string;
export type Entities2 = Entity[];
export type RefinedActions = RefinedAction[];
export type SchemaVersion53 = "0.2.0";
export type ShotId10 = string;
export type WorldFrame3 = string;
export type FrameIndex9 = number;
export type Timestamp6 = number;
export type CameraFrameIndex = number | null;
export type SchemaVersion54 = "0.2.0";
export type EntityId6 = string;
export type TrackId3 = string;
export type Origin4 = "estimated" | "synthetic" | "missing";
export type Representation1 = string;
export type Hands1 = InteractionPose[];
export type Objects1 = InteractionPose[];
export type Contacts1 = ContactFrame[];
export type CurrentActionIds = string[];
export type Frames = InteractionFrame[];
export type ScaleMode2 = "relative";
export type MetricScaleValid5 = false;

export interface ActionGraph {
  schema_version?: SchemaVersion;
  nodes: Nodes;
  edges: Edges;
}
export interface Edge {
  schema_version?: SchemaVersion1;
  source: Source;
  target: Target;
  reason: Reason;
}
export interface ArtifactManifest {
  schema_version?: SchemaVersion2;
  artifact_id: ArtifactId;
  uri: Uri;
  sha256: Sha256;
  byte_count: ByteCount;
  media_type: MediaType;
  stage: Stage;
  run_id: RunId;
  input_hashes: InputHashes;
  config_hash: ConfigHash;
  code_hash: CodeHash;
  model?: Model;
  model_revision?: ModelRevision;
  prompt_hash?: PromptHash;
  created_at: CreatedAt;
  inference_mode: InferenceMode;
}
export interface Correction {
  schema_version?: SchemaVersion3;
  source_job_id: SourceJobId;
  entity_id: EntityId;
  shot_id: ShotId;
  frame_index: FrameIndex;
  kind: Kind;
  point?: Point;
  bbox_xyxy?: BboxXyxy;
  provider_track_id?: ProviderTrackId;
}
export interface Entity {
  schema_version?: SchemaVersion4;
  entity_id: EntityId1;
  category: Category;
  semantic_name: SemanticName;
  sam_prompt: SamPrompt;
  role: Role;
  motion: Motion;
  handedness?: Handedness;
  visibility_intervals?: VisibilityIntervals;
  confidence?: Confidence;
  uncertainty_reasons?: UncertaintyReasons;
}
export interface Interval {
  schema_version?: SchemaVersion5;
  start_s: StartS;
  end_s: EndS;
}
export interface ErrorResponse {
  schema_version?: SchemaVersion6;
  code: Code;
  message: Message;
  retryable: Retryable;
}
export interface JobEvent {
  schema_version?: SchemaVersion7;
  sequence: Sequence;
  job_id: JobId;
  status: Status;
  stage: Stage1;
  created_at: CreatedAt1;
  detail?: Detail;
}
export interface Detail {
  [k: string]: unknown;
}
export interface LayerOneHandoffManifest {
  schema_version?: SchemaVersion8;
  video_id: VideoId;
  run_id: RunId1;
  inference_mode: InferenceMode1;
  artifacts: Artifacts;
  entities: Entities;
  ready_for_geometry: ReadyForGeometry;
  review_reasons: ReviewReasons;
  metric_scale_valid?: MetricScaleValid;
  coordinates?: Coordinates;
  certification?: Certification;
}
export interface Artifacts {
  [k: string]: string;
}
export interface ModelRun {
  schema_version?: SchemaVersion9;
  model_run_id: ModelRunId;
  model: Model1;
  revision?: Revision;
  stage: Stage2;
  inference_mode: InferenceMode2;
  input_hash: InputHash;
  config_hash: ConfigHash1;
  prompt_hash: PromptHash1;
  status: Status1;
  request_id?: RequestId;
  latency_ms?: LatencyMs;
  usage?: Usage;
  actual_cost_usd?: ActualCostUsd;
  estimated_cost_usd?: EstimatedCostUsd;
  attempt?: Attempt;
  warnings?: Warnings;
  error?: Error;
}
export interface Usage {
  [k: string]: unknown;
}
export interface ProcessRequest {
  schema_version?: SchemaVersion10;
  idempotency_key: IdempotencyKey;
}
export interface Provenance {
  schema_version?: SchemaVersion11;
  source_uri?: SourceUri;
  rights_status: RightsStatus;
  license?: License;
  consent?: Consent;
  uploader?: Uploader;
}
export interface SemanticPlan {
  schema_version?: SchemaVersion12;
  task: Task;
  canonical_skill: CanonicalSkill;
  duration_s: DurationS;
  entities: Entities1;
  actions: Actions;
  action_graph: ActionGraph;
  warnings?: Warnings1;
}
export interface ActionSegment {
  schema_version?: SchemaVersion13;
  start_s: StartS1;
  end_s: EndS1;
  action_id: ActionId;
  primitive: Primitive;
  actor?: Actor;
  object?: Object;
  target?: Target1;
  part?: Part;
  timing_source?: TimingSource;
  requires_contact?: RequiresContact;
  preconditions?: Preconditions;
  effects?: Effects;
  confidence?: Confidence1;
  uncertainty_reasons?: UncertaintyReasons1;
}
export interface Predicate {
  schema_version?: SchemaVersion14;
  relation: Relation;
  entity_ids: EntityIds;
  negated?: Negated;
}
export interface StageResult {
  schema_version?: SchemaVersion15;
  stage: Stage3;
  run_id: RunId2;
  status: Status2;
  artifact_ids: ArtifactIds;
  warnings: Warnings2;
  error?: Error1;
}
export interface TrackFrame {
  schema_version?: SchemaVersion16;
  video_id: VideoId1;
  shot_id: ShotId1;
  frame_index: FrameIndex1;
  timestamp: Timestamp;
  source_timestamp: SourceTimestamp;
  entity_id: EntityId2;
  track_id: TrackId;
  provider_track_id?: ProviderTrackId1;
  mask_ref?: MaskRef;
  bbox_xyxy?: BboxXyxy1;
  centroid?: Centroid;
  centroid_normalized?: CentroidNormalized;
  provider_confidence?: ProviderConfidence;
  tracking_confidence?: TrackingConfidence;
  observed: Observed;
  visibility: Visibility;
  origin: Origin;
  identity_status: IdentityStatus;
  warnings?: Warnings3;
  model_run_id: ModelRunId1;
}
export interface TrackSummary {
  schema_version?: SchemaVersion17;
  entity_id: EntityId3;
  track_id: TrackId1;
  observed_frame_coverage: ObservedFrameCoverage;
  expected_visible_frame_coverage?: ExpectedVisibleFrameCoverage;
  missing_frames: MissingFrames;
  longest_missing_run: LongestMissingRun;
  reinitializations: Reinitializations;
  verified_id_switches?: VerifiedIdSwitches;
  anomaly_count: AnomalyCount;
  identity_status: IdentityStatus1;
}
export interface UploadRequest {
  schema_version?: SchemaVersion18;
  filename: Filename;
  byte_count: ByteCount1;
  sha256: Sha2561;
  provenance: Provenance;
}
export interface VideoAsset {
  schema_version?: SchemaVersion19;
  video_id: VideoId2;
  original_ref: OriginalRef;
  source_hash: SourceHash;
  byte_count: ByteCount2;
  provenance: Provenance;
}
export interface VideoManifest {
  schema_version?: SchemaVersion20;
  video_id: VideoId3;
  original: Original;
  normalized_ref: NormalizedRef;
  width: Width;
  height: Height;
  fps_num: FpsNum;
  fps_den?: FpsDen;
  frame_count: FrameCount;
  duration_s: DurationS1;
  pixel_format?: PixelFormat;
  normalization_hash: NormalizationHash;
  frame_map_ref: FrameMapRef;
  shots: Shots;
  keyframe_refs: KeyframeRefs;
  diagnostics: Diagnostics;
}
export interface Original {
  [k: string]: unknown;
}
export interface Shot {
  schema_version?: SchemaVersion21;
  shot_id: ShotId2;
  start_frame: StartFrame;
  end_frame: EndFrame;
}
export interface Diagnostics {
  [k: string]: unknown;
}
export interface ArtifactsResponse {
  schema_version?: SchemaVersion22;
  run_id: RunId3;
  inference_mode: InferenceMode3;
  artifacts: Artifacts1;
}
export interface ArtifactView {
  schema_version?: SchemaVersion23;
  artifact_id: ArtifactId1;
  uri: Uri1;
  sha256: Sha2562;
  byte_count: ByteCount3;
  media_type: MediaType1;
  stage: Stage4;
  run_id: RunId4;
  input_hashes: InputHashes1;
  config_hash: ConfigHash2;
  code_hash: CodeHash1;
  model?: Model2;
  model_revision?: ModelRevision1;
  prompt_hash?: PromptHash2;
  created_at: CreatedAt2;
  inference_mode: InferenceMode4;
  name: Name;
  url: Url;
}
export interface HealthResponse {
  schema_version?: SchemaVersion24;
  status: Status3;
  inference_mode: InferenceMode5;
  scope?: Scope;
}
export interface JobDetail {
  schema_version?: SchemaVersion25;
  job_id: JobId1;
  video_id: VideoId4;
  run_id: RunId5;
  status: Status4;
  stage: Stage5;
  inference_mode: InferenceMode6;
  pipeline?: Pipeline;
  error?: Error2;
  source_job_id?: SourceJobId1;
  created_at: CreatedAt3;
  stages: Stages;
  model_runs: ModelRuns;
}
export interface StageView {
  schema_version?: SchemaVersion26;
  stage: Stage6;
  attempt: Attempt1;
  status: Status5;
  error: Error3;
}
export interface ModelRunView {
  schema_version?: SchemaVersion27;
  model_run_id: ModelRunId2;
  model: Model3;
  revision?: Revision1;
  stage: Stage7;
  inference_mode: InferenceMode7;
  input_hash: InputHash1;
  config_hash: ConfigHash3;
  prompt_hash: PromptHash3;
  status: Status6;
  request_id?: RequestId1;
  latency_ms?: LatencyMs1;
  usage?: Usage1;
  actual_cost_usd?: ActualCostUsd1;
  estimated_cost_usd?: EstimatedCostUsd1;
  attempt?: Attempt2;
  warnings?: Warnings4;
  error?: Error4;
  raw_ref?: RawRef;
}
export interface Usage1 {
  [k: string]: unknown;
}
export interface JobView {
  schema_version?: SchemaVersion28;
  job_id: JobId2;
  video_id: VideoId5;
  run_id: RunId6;
  status: Status7;
  stage: Stage8;
  inference_mode: InferenceMode8;
  pipeline?: Pipeline1;
  error?: Error5;
  source_job_id?: SourceJobId2;
  created_at: CreatedAt4;
}
export interface TrackingReport {
  schema_version?: SchemaVersion29;
  inference_mode: InferenceMode9;
  calibration: Calibration;
  summaries: Summaries;
  anchors: Anchors;
  review_reasons: ReviewReasons1;
  mask_bundles: MaskBundles;
  reprojection: Reprojection;
  physical_feasibility: PhysicalFeasibility;
}
export interface Anchor {
  schema_version?: SchemaVersion30;
  entity_id: EntityId4;
  shot_id: ShotId3;
  frame_index: FrameIndex2;
  mask_ref: MaskRef1;
  method: Method;
}
export interface TracksResponse {
  schema_version?: SchemaVersion31;
  total: Total;
  offset: Offset;
  tracks: Tracks;
  masks: Masks;
}
export interface Masks {
  [k: string]: RLEMask;
}
export interface RLEMask {
  schema_version?: SchemaVersion32;
  encoding: Encoding;
  height: Height1;
  width: Width1;
  counts: Counts;
}
export interface UploadCompleteResponse {
  schema_version?: SchemaVersion33;
  video_id: VideoId6;
  status: Status8;
  probe?: Probe;
}
export interface UploadResponse {
  schema_version?: SchemaVersion34;
  video_id: VideoId7;
  upload_url: UploadUrl;
  upload_headers: UploadHeaders;
  expires_in: ExpiresIn;
  inference_mode: InferenceMode10;
}
export interface UploadHeaders {
  [k: string]: string;
}
export interface VideoDetail {
  schema_version?: SchemaVersion35;
  video_id: VideoId8;
  filename: Filename1;
  status: Status9;
  provenance: Provenance;
  probe: Probe1;
  jobs: Jobs;
  source_url: SourceUrl;
}
export interface VideoListResponse {
  schema_version?: SchemaVersion36;
  videos: Videos;
}
export interface VideoListItem {
  schema_version?: SchemaVersion37;
  video_id: VideoId9;
  filename: Filename2;
  status: Status10;
}
export interface ReconstructionRequest {
  schema_version?: SchemaVersion38;
  source_job_id: SourceJobId3;
  idempotency_key: IdempotencyKey1;
  config?: ReconstructionConfig;
  allow_review_source?: AllowReviewSource;
}
export interface ReconstructionConfig {
  schema_version?: SchemaVersion39;
  backend?: Backend;
  body_backend?: BodyBackend;
  sample_fps?: SampleFps;
  max_frames_per_shot?: MaxFramesPerShot;
  max_total_frames?: MaxTotalFrames;
  max_points_per_entity?: MaxPointsPerEntity;
  contact_distance_2d_px?: ContactDistance2DPx;
  contact_distance_3d_relative?: ContactDistance3DRelative;
  contact_on?: ContactOn;
  contact_off?: ContactOff;
  persistence_frames?: PersistenceFrames;
  boundary_window_s?: BoundaryWindowS;
  max_alignment_relative_rmse?: MaxAlignmentRelativeRmse;
}
export interface Pose3D {
  schema_version?: SchemaVersion40;
  position_xyz: PositionXyz;
  quaternion_xyzw?: QuaternionXyzw;
  confidence?: Confidence2;
  metric_scale_valid?: MetricScaleValid1;
}
export interface Alignment {
  schema_version?: SchemaVersion41;
  alignment_id: AlignmentId;
  source_frame: SourceFrame;
  target_frame: TargetFrame;
  rotation: Rotation;
  translation: Translation;
  scale: Scale;
  rmse: Rmse;
  correspondence_count: CorrespondenceCount;
  method: Method1;
  uncertainty?: Uncertainty;
}
export interface CameraFrame {
  schema_version?: SchemaVersion42;
  video_id: VideoId10;
  shot_id: ShotId4;
  frame_index: FrameIndex3;
  timestamp: Timestamp1;
  world_frame: WorldFrame;
  intrinsic: Intrinsic;
  world_from_camera: WorldFromCamera;
  image_width: ImageWidth;
  image_height: ImageHeight;
  source: Source1;
  origin: Origin1;
  metric_scale_valid?: MetricScaleValid2;
}
export interface PoseFrame {
  schema_version?: SchemaVersion43;
  video_id: VideoId11;
  shot_id: ShotId5;
  frame_index: FrameIndex4;
  timestamp: Timestamp2;
  entity_id: EntityId5;
  track_id: TrackId2;
  world_frame: WorldFrame1;
  pose?: Pose3D | null;
  points_world?: PointsWorld;
  keypoint_names?: KeypointNames;
  keypoints_world?: KeypointsWorld;
  linear_velocity?: LinearVelocity;
  angular_velocity?: AngularVelocity;
  projected_centroid?: ProjectedCentroid;
  reprojection_error_px?: ReprojectionErrorPx;
  origin: Origin2;
  representation: Representation;
  orientation_status?: OrientationStatus;
  source: Source2;
  alignment_id?: AlignmentId1;
  warnings?: Warnings5;
}
export interface RelativeFrame {
  schema_version?: SchemaVersion44;
  shot_id: ShotId6;
  frame_index: FrameIndex5;
  timestamp: Timestamp3;
  world_frame: WorldFrame2;
  hand_id: HandId;
  object_id: ObjectId;
  hand_track_id: HandTrackId;
  object_track_id: ObjectTrackId;
  hand_in_object?: Pose3D | null;
  relative_position_world_xyz?: RelativePositionWorldXyz;
  object_delta?: Pose3D | null;
  origin: Origin3;
  warnings?: Warnings6;
}
export interface ContactFrame {
  schema_version?: SchemaVersion45;
  shot_id: ShotId7;
  frame_index: FrameIndex6;
  timestamp: Timestamp4;
  hand_id: HandId1;
  object_id: ObjectId1;
  hand_track_id?: HandTrackId1;
  object_track_id?: ObjectTrackId1;
  state: State;
  probability?: Probability;
  probability_calibrated?: ProbabilityCalibrated;
  distance_2d_px?: Distance2DPx;
  distance_3d_relative?: Distance3DRelative;
  geometry_age_s?: GeometryAgeS;
  geometry_origin?: GeometryOrigin;
  motion_coupling?: MotionCoupling;
  semantic_prior?: SemanticPrior;
  contact_points_object?: ContactPointsObject;
  evidence_origin: EvidenceOrigin;
  warnings?: Warnings7;
}
export interface InteractionEvent {
  schema_version?: SchemaVersion46;
  event_id: EventId;
  shot_id: ShotId8;
  frame_index: FrameIndex7;
  timestamp: Timestamp5;
  hand_id: HandId2;
  object_id: ObjectId2;
  kind: Kind1;
  confidence?: Confidence3;
  validated_grasp?: ValidatedGrasp;
  reasons: Reasons;
}
export interface RefinedAction {
  schema_version?: SchemaVersion47;
  action_id: ActionId1;
  primitive: Primitive;
  semantic_start_s: SemanticStartS;
  semantic_end_s: SemanticEndS;
  refined_start_s?: RefinedStartS;
  refined_end_s?: RefinedEndS;
  timing_source?: TimingSource1;
  evidence_event_ids?: EvidenceEventIds;
  review_reasons?: ReviewReasons2;
}
export interface AffordancePatch {
  schema_version?: SchemaVersion48;
  object_id: ObjectId3;
  hand_id: HandId3;
  shot_id: ShotId9;
  frame_index: FrameIndex8;
  primitive?: Primitive1;
  part_name?: PartName;
  contact_patch_object_xyz: ContactPatchObjectXyz;
  approach_direction?: ApproachDirection;
  observed_grasp?: ObservedGrasp;
  source: Source3;
}
export interface ReconstructionReport {
  schema_version?: SchemaVersion49;
  source_run_id: SourceRunId;
  backend: Backend1;
  inference_mode: InferenceMode11;
  scale_mode?: ScaleMode;
  metric_scale_valid?: MetricScaleValid3;
  world_frames: WorldFrames;
  sampled_frames: SampledFrames;
  camera_frames: CameraFrames;
  hand_pose_frames: HandPoseFrames;
  object_pose_frames: ObjectPoseFrames;
  relative_pose_frames: RelativePoseFrames;
  contact_frames?: ContactFrames;
  contact_events?: ContactEvents;
  reprojection_median_px?: ReprojectionMedianPx;
  reprojection_metric?: ReprojectionMetric;
  review_reasons: ReviewReasons3;
  physical_feasibility?: PhysicalFeasibility1;
}
export interface LayerTwoHandoff {
  schema_version?: SchemaVersion50;
  video_id: VideoId12;
  run_id: RunId7;
  source_run_id: SourceRunId1;
  inference_mode: InferenceMode12;
  artifacts: Artifacts2;
  ready_for_robotization: ReadyForRobotization;
  metric_scale_valid?: MetricScaleValid4;
  scale_mode?: ScaleMode1;
  certification?: Certification1;
  review_reasons: ReviewReasons4;
  coordinates?: Coordinates1;
}
export interface Artifacts2 {
  [k: string]: string;
}
export interface GeometryWindow {
  schema_version?: SchemaVersion51;
  total: Total1;
  offset: Offset1;
  cameras?: Cameras;
  hands?: Hands;
  objects?: Objects;
  relative?: Relative;
  contacts?: Contacts;
}
export interface InteractionTrajectory {
  schema_version?: SchemaVersion52;
  video_id: VideoId13;
  run_id: RunId8;
  source_run_id: SourceRunId2;
  task: Task1;
  canonical_skill: CanonicalSkill1;
  entities: Entities2;
  action_graph: ActionGraph;
  refined_actions: RefinedActions;
  frames: Frames;
  scale_mode?: ScaleMode2;
  metric_scale_valid?: MetricScaleValid5;
  quality: ReconstructionReport;
}
export interface InteractionFrame {
  schema_version?: SchemaVersion53;
  shot_id: ShotId10;
  world_frame: WorldFrame3;
  frame_index: FrameIndex9;
  timestamp: Timestamp6;
  camera_frame_index?: CameraFrameIndex;
  hands: Hands1;
  objects: Objects1;
  contacts: Contacts1;
  current_action_ids: CurrentActionIds;
}
export interface InteractionPose {
  schema_version?: SchemaVersion54;
  entity_id: EntityId6;
  track_id: TrackId3;
  pose: Pose3D | null;
  origin: Origin4;
  representation: Representation1;
}
