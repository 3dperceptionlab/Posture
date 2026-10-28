"""Versioned HMI/ROS contracts, independent of laboratory capture controls."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, field_serializer, model_validator
from .vision_common import JOINT_NAMES

Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Vector3 = Annotated[list[Annotated[float, Field(strict=True)]], Field(min_length=3, max_length=3)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    @field_serializer('*', mode='wrap')
    def serialize_utc(self, value, handler):
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
        return handler(value)

    @field_validator('*')
    @classmethod
    def utc(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError('El timestamp debe incluir zona horaria.')
            return value.astimezone(timezone.utc)
        return value


class Operator(Contract):
    id: str | StrictInt
    name: Annotated[str, Field(min_length=1, max_length=200)]
    stature_m: Annotated[float, Field(ge=1, le=2.3)] | None = None
    profile: dict = Field(default_factory=dict, description='Configuración HMI original; no se aplica desde el servidor.')

    @field_validator('id')
    @classmethod
    def valid_id(cls, value):
        if not str(value).strip() or len(str(value)) > 128:
            raise ValueError('ID de operario vacío o demasiado largo.')
        return value


class Assessment(Contract):
    form_id: Identifier
    submitted_at: datetime
    answers: dict = Field(default_factory=dict)


class ShiftStart(Contract):
    schema_version: Literal['1.0'] = '1.0'
    source_id: Identifier
    cell_id: Identifier = 'cell-real-01'
    client_shift_id: Identifier
    started_at: datetime
    operator: Operator
    assessment: Assessment
    label: Annotated[str, Field(max_length=200)] = ''
    metadata: dict = Field(default_factory=dict)


class ShiftEnd(Contract):
    ended_at: datetime
    assessment: Assessment
    status: Literal['completed', 'aborted', 'error'] = 'completed'
    reason: Annotated[str, Field(max_length=2000)] = ''
    metadata: dict = Field(default_factory=dict)


class IterationStart(Contract):
    schema_version: Literal['1.0'] = '1.0'
    source_id: Identifier
    cell_id: Identifier = 'cell-real-01'
    client_iteration_id: Identifier
    shift_id: Annotated[StrictInt, Field(ge=1)]
    started_at: datetime
    operator: Operator
    robot_assisted: bool | None = None
    label: Annotated[str, Field(max_length=200)] = ''
    metadata: dict = Field(default_factory=dict)


class Space(Contract):
    kind: Literal['unknown', 'model_relative', 'camera_metric', 'world_metric']
    frame_id: Identifier
    unit: Literal['m', 'mm', 'unknown']
    axes: Literal['optical', 'ros', 'unknown']
    rotation_unit: Literal['rad', 'deg', 'unknown']
    rotation_convention: Literal['extrinsic_xyz', 'unknown']


class Joint(Contract):
    status: Literal['detected', 'estimated', 'missing'] = 'detected'
    position: Vector3 | None = None
    rotation_xyz: Vector3 | None = None
    image_xy_px: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None

    @model_validator(mode='after')
    def coordinates(self):
        if self.status == 'missing' and any(v is not None for v in (self.position, self.rotation_xyz, self.image_xy_px)):
            raise ValueError('Un joint ausente debe tener coordenadas y rotación nulas.')
        if self.status != 'missing' and self.position is None and self.image_xy_px is None:
            raise ValueError('Un joint detectado/estimado necesita posición 3D o coordenadas de imagen.')
        return self


class Pose(Contract):
    joint_schema: Literal['posture.body33.v1'] = 'posture.body33.v1'
    estimator_name: Identifier
    estimator_version: Identifier
    space: Space
    joints: dict[str, Joint]

    @field_validator('joints')
    @classmethod
    def body33(cls, value):
        if set(value) != set(JOINT_NAMES):
            raise ValueError('Se requieren las 33 claves de posture.body33.v1, también las ausentes.')
        return value


class ToolPose(Contract):
    observed_at: datetime
    position: Vector3
    rotation_xyz: Vector3
    space: Space
    suction_commanded: bool | None = None


class TableState(Contract):
    observed_at: datetime
    height_m: Annotated[float, Field(ge=0, le=3)] | None = None
    position: Vector3 | None = None
    rotation_xyz: Vector3 | None = None
    space: Space | None = None
    measurement: Literal['measured', 'commanded', 'unknown'] = 'unknown'


class Sample(Contract):
    schema_version: Literal['1.0'] = '1.0'
    sequence: Annotated[StrictInt, Field(ge=0)]
    captured_at: datetime
    frame_id: Identifier
    video_time_s: Annotated[float, Field(ge=0)]
    image_width: Annotated[StrictInt, Field(ge=1, le=8192)]
    image_height: Annotated[StrictInt, Field(ge=1, le=8192)]
    mirrored: bool = False
    source_frame_index: Annotated[StrictInt, Field(ge=0)] | None = None
    pose: Pose
    tool: ToolPose | None = None
    table: TableState | None = None
    metadata: dict = Field(default_factory=dict)


class Action(Contract):
    event_id: Identifier
    observed_at: datetime
    type: Identifier
    message: Annotated[str, Field(max_length=2000)] = ''
    data: dict = Field(default_factory=dict)


class Summary(Contract):
    ended_at: datetime
    status: Literal['completed', 'aborted', 'error', 'rejected'] = 'completed'
    completion_reason: Identifier = 'quality_check'
    actions: Annotated[list[Action], Field(max_length=5000)] = Field(default_factory=list)
    final_tool: ToolPose | None = None
    final_table: TableState | None = None
    metadata: dict = Field(default_factory=dict)


class VideoStart(Contract):
    size_bytes: Annotated[StrictInt, Field(gt=0, le=2 * 1024**3)]
    sha256: Annotated[str, Field(pattern='^[a-f0-9]{64}$')]
    recorded_at: datetime = Field(description='UTC del primer fotograma, cuya posición relativa en el MP4 es cero.')


class AnalysisRequest(Contract):
    client_analysis_id: Identifier
    sources: Annotated[list[Literal['ros', 'video']], Field(min_length=1, max_length=2)] = ['ros', 'video']
    sample_fps: Annotated[float, Field(ge=1, le=25)] = 5
    confidence: Annotated[float, Field(ge=.5, le=.9)] = .5

    @field_validator('sources')
    @classmethod
    def unique_sources(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('sources no puede contener duplicados.')
        return value


class LabelUpdate(Contract):
    label: Annotated[str, Field(max_length=200)]


class Settings(Contract):
    expected_revision: Annotated[StrictInt, Field(ge=1)]
    ros_metrics_mode: Literal['manual', 'live', 'after_iteration'] = 'manual'
    video_analysis_mode: Literal['manual', 'when_ready'] = 'manual'
    sample_fps: Annotated[float, Field(ge=1, le=25)] = 5
    confidence: Annotated[float, Field(ge=.5, le=.9)] = .5
    assessment_form_id: Identifier = 'posture.shift-checkin.v1'


class Question(Contract):
    key: Identifier
    label: Annotated[str, Field(min_length=1, max_length=300)]
    type: Literal['scale', 'text', 'choice'] = 'scale'
    minimum: float = 0
    maximum: float = 10
    choices: Annotated[list[str], Field(max_length=30)] = Field(default_factory=list)
    required: bool = False
    phases: list[Literal['pre', 'post']] = ['pre', 'post']

    @model_validator(mode='after')
    def bounds(self):
        if self.minimum >= self.maximum or not self.phases or (self.type == 'choice' and not self.choices):
            raise ValueError('Límites, fases u opciones inválidos.')
        return self


class FormDefinition(Contract):
    form_id: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(max_length=2000)] = ''
    questions: Annotated[list[Question], Field(max_length=30)]

    @field_validator('questions')
    @classmethod
    def unique_keys(cls, value):
        if len({q.key for q in value}) != len(value):
            raise ValueError('Las claves de preguntas deben ser únicas.')
        return value


class ReadModel(Contract):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)


class ShiftRead(ReadModel):
    shift_id: int
    client_shift_id: str
    source_id: str
    cell_id: str
    operator_id: str
    external_operator_id: str
    operator: Operator
    started_at: datetime
    ended_at: datetime | None
    status: str
    label: str
    assessment: Assessment
    form_definition: FormDefinition


class IterationRead(ReadModel):
    iteration_id: int
    shift_id: int
    client_iteration_id: str
    source_id: str
    cell_id: str
    operator_id: str
    external_operator_id: str
    operator: Operator
    started_at: datetime
    ended_at: datetime | None
    robot_assisted: bool | None
    label: str
    status: str
    sample_count: int
    video_status: str
    summary_received: bool
    policies: dict


class SampleRead(Sample):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    iteration_id: int
    shift_id: int
    operator_id: str
    received_at: datetime
    image_sha256: str


class SampleReceipt(ReadModel):
    status: Literal['accepted','duplicate']
    durable: bool
    iteration_id: int
    shift_id: int
    sequence: int


class AnalysisRead(ReadModel):
    analysis_id: str
    iteration_id: int
    shift_id: int
    source: Literal['ros','video']
    status: str
    processed_frames: int
    evaluable_frames: int
    created_at: datetime
    error: str | None
