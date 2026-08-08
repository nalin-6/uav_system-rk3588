"""Hailo-8L NPU YOLO detector for Raspberry Pi 5 + Hailo-8L PCIe."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

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


class HailoDetector:
    """Hailo-8L NPU YOLO detector with NMS built into the HEF model."""

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
            raise FileNotFoundError(f"HEF model not found: {model_path}")
        if model.suffix.lower() != ".hef":
            raise ValueError(f"HailoDetector requires .hef model: {model_path}")

        from hailo_platform import (
            HEF,
            VDevice,
            ConfigureParams,
            HailoStreamInterface,
            InputVStreamParams,
            OutputVStreamParams,
        )

        self._conf = conf_thres
        self._classes = set(classes) if classes else None
        self._class_names = class_names

        # Load HEF and configure NPU
        self._hef = HEF(str(model))
        self._vdevice = VDevice()

        self._input_info = self._hef.get_input_vstream_infos()[0]
        output_infos = self._hef.get_output_vstream_infos()

        self._input_h = self._input_info.shape[0]
        self._input_w = self._input_info.shape[1]

        configure_params = ConfigureParams.create_from_hef(
            self._hef, interface=HailoStreamInterface.PCIe
        )
        self._network_group = self._vdevice.configure(self._hef, configure_params)[0]
        self._input_params = InputVStreamParams.make(self._network_group)
        self._output_params = OutputVStreamParams.make(self._network_group)
        self._output_name = output_infos[0].name

    def detect(self, frame: np.ndarray) -> list[Detection]:
        from hailo_platform import InferVStreams

        img_h, img_w = frame.shape[:2]

        # Preprocess: letterbox + BGR->RGB
        padded, ratio, pad = _letterbox(frame, self._input_w, self._input_h)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        model_input = rgb[np.newaxis, ...]

        # NPU inference (network group must be activated)
        with self._network_group.activate():
            with InferVStreams(
                self._network_group, self._input_params, self._output_params
            ) as pipeline:
                results = pipeline.infer({self._input_info.name: model_input})

        # Parse NMS output: list[batch=1][class_id] -> ndarray(N, 5)
        # 5 = [y1, x1, y2, x2, score], coordinates normalized [0, 1]
        output_data = results[self._output_name]
        detections: list[Detection] = []

        if isinstance(output_data, list):
            batch_data = output_data[0]
            if isinstance(batch_data, list):
                for class_id, class_dets in enumerate(batch_data):
                    if not isinstance(class_dets, np.ndarray) or class_dets.size == 0:
                        continue
                    if self._classes is not None and class_id not in self._classes:
                        continue
                    for j in range(class_dets.shape[0]):
                        score = float(class_dets[j, 4])
                        if score < self._conf:
                            continue
                        # Coordinates are in letterbox-padded space, normalized
                        ny1, nx1, ny2, nx2 = (
                            float(class_dets[j, k]) for k in range(4)
                        )
                        # Denormalize to letterbox pixel space
                        px1 = nx1 * self._input_w
                        py1 = ny1 * self._input_h
                        px2 = nx2 * self._input_w
                        py2 = ny2 * self._input_h
                        # Reverse letterbox to original image space
                        ox1 = max(0.0, (px1 - pad[0]) / ratio)
                        oy1 = max(0.0, (py1 - pad[1]) / ratio)
                        ox2 = min(float(img_w), (px2 - pad[0]) / ratio)
                        oy2 = min(float(img_h), (py2 - pad[1]) / ratio)

                        name = (
                            self._class_names[class_id]
                            if class_id < len(self._class_names)
                            else str(class_id)
                        )
                        detections.append(
                            Detection(
                                class_id=class_id,
                                class_name=name,
                                confidence=score,
                                x1=ox1,
                                y1=oy1,
                                x2=ox2,
                                y2=oy2,
                            )
                        )
        return detections

    def release(self) -> None:
        del self._network_group
        del self._vdevice
        del self._hef
