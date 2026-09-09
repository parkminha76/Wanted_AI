# train.py
from ultralytics import YOLO

model = YOLO("yolov8n.pt")
model.train(
    data="data.yaml", epochs=30, imgsz=640, batch=16, patience=10,
    project="C:/wanted/runs/detect", name="infoguard_v1",
)