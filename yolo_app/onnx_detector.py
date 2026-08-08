from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

INPUT_SIZE = 640
CLASS_NAMES = (
    "baozha", "shenghua", "yiran", "fangshe", "buran",
    "fushi", "youdu", "yushi", "ziran", "ciji", "bucket",
)


@dataclass(slots=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


def _letterbox(img, new_shape=INPUT_SIZE, color=(114, 114, 114)):
    shape = img.shape[:2]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    new_unpad = (int(round(shape[1] * r)), int(round(shape[0] * r)))
    dw = (new_shape[1] - new_unpad[0]) / 2
    dh = (new_shape[0] - new_unpad[1]) / 2
    if shape[::-1] != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_AREA)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right,
                             cv2.BORDER_CONSTANT, value=color)
    return img, r, (dw, dh)


def _xywh2xyxy(x):
    y = np.copy(x)
    y[:, 0] = x[:, 0] - x[:, 2] / 2
    y[:, 1] = x[:, 1] - x[:, 3] / 2
    y[:, 2] = x[:, 0] + x[:, 2] / 2
    y[:, 3] = x[:, 1] + x[:, 3] / 2
    return y


class OnnxDetector:
    """ONNX Runtime YOLO detector for CPU inference (Raspberry Pi 5)."""

    def __init__(
        self,
        model_path: str,
        conf_thres: float,
        iou_thres: float,
        classes: list[int],
        class_names: tuple[str, ...] = CLASS_NAMES,
    ) -> None:
        model = Path(model_path)
        if not model.exists():
            raise FileNotFoundError(f"ONNX model not found: {model_path}")
        if model.suffix.lower() != ".onnx":
            raise ValueError(f"ONNX detector requires .onnx model: {model_path}")

        self._session = ort.InferenceSession(
            str(model), providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        self._conf = conf_thres
        self._iou = iou_thres
        self._classes = set(classes) if classes else None
        self._class_names = class_names

    def detect(self, frame: np.ndarray) -> list[Detection]:
        img_h, img_w = frame.shape[:2]

        # Preprocess: letterbox + BGR->RGB + HWC->CHW + normalize
        padded, ratio, pad = _letterbox(frame, INPUT_SIZE)
        blob = padded[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        blob = np.expand_dims(blob, axis=0)

        # Inference
        outputs = self._session.run(None, {self._input_name: blob})
        predictions = outputs[0][0].T  # (N, 84)

        # Split boxes and scores
        boxes_xywh = predictions[:, :4]
        class_scores = predictions[:, 4:]
        max_scores = class_scores.max(axis=1)
        class_ids = class_scores.argmax(axis=1)

        # Filter by confidence
        mask = max_scores >= self._conf
        if self._classes is not None:
            mask &= np.array([cid in self._classes for cid in class_ids])
        if not np.any(mask):
            return []

        boxes_xywh = boxes_xywh[mask]
        max_scores = max_scores[mask]
        class_ids = class_ids[mask]

        # Convert xywh -> xyxy
        boxes_xyxy = _xywh2xyxy(boxes_xywh)

        # Scale back to original image coordinates
        boxes_xyxy[:, [0, 2]] -= pad[0]
        boxes_xyxy[:, [1, 3]] -= pad[1]
        boxes_xyxy /= ratio

        # Clip to image bounds
        boxes_xyxy[:, [0, 2]] = np.clip(boxes_xyxy[:, [0, 2]], 0, img_w - 1)
        boxes_xyxy[:, [1, 3]] = np.clip(boxes_xyxy[:, [1, 3]], 0, img_h - 1)

        # NMS
        xywh_for_nms = np.column_stack((
            boxes_xyxy[:, 0], boxes_xyxy[:, 1],
            boxes_xyxy[:, 2] - boxes_xyxy[:, 0],
            boxes_xyxy[:, 3] - boxes_xyxy[:, 1],
        ))
        indices = cv2.dnn.NMSBoxes(
            xywh_for_nms.astype(np.float32).tolist(),
            max_scores.astype(float).tolist(),
            self._conf,
            self._iou,
        )

        detections = []
        for idx in np.asarray(indices).reshape(-1):
            x1, y1, x2, y2 = boxes_xyxy[idx]
            cid = int(class_ids[idx])
            name = self._class_names[cid] if cid < len(self._class_names) else str(cid)
            detections.append(Detection(
                class_id=cid,
                class_name=name,
                confidence=float(max_scores[idx]),
                x1=float(x1),
                y1=float(y1),
                x2=float(x2),
                y2=float(y2),
            ))
        return detections

    def release(self) -> None:
        del self._session
