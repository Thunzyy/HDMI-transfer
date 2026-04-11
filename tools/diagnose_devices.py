"""Quick diagnostic: identify which MSMF index is which physical device."""
import cv2
import numpy as np
import sys

print("=== DSHOW Device Fingerprints ===")
for i in range(5):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if not cap.isOpened():
        continue
    dw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    dh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    dfps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    print(f"  DSHOW [{i}]: default {dw}x{dh} @ {dfps:.0f}fps")

print("\n=== MSMF Device Fingerprints ===")
for i in range(5):
    cap = cv2.VideoCapture(i, cv2.CAP_MSMF)
    if not cap.isOpened():
        continue
    dw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    dh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    dfps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    print(f"  MSMF  [{i}]: default {dw}x{dh} @ {dfps:.0f}fps")

print("\n=== MSMF Frame Test (read 1 frame each) ===")
for i in range(5):
    cap = cv2.VideoCapture(i, cv2.CAP_MSMF)
    if not cap.isOpened():
        continue
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    afps = cap.get(cv2.CAP_PROP_FPS)
    ret, frame = cap.read()
    if ret and isinstance(frame, np.ndarray):
        brightness = frame.mean()
        # Check if it looks like colored blocks (sender) vs natural image (webcam)
        # Sender frames have very high contrast (0 or 255 values)
        std_dev = frame.std()
        unique_colors = len(np.unique(frame.reshape(-1, 3), axis=0))
        print(f"  MSMF [{i}]: {aw}x{ah}@{afps:.0f}fps | "
              f"brightness={brightness:.1f} std={std_dev:.1f} "
              f"unique_colors={unique_colors} "
              f"{'ALL-BLACK' if brightness < 5 else 'HAS-SIGNAL'}")
        # Save thumbnail for visual inspection
        thumb = cv2.resize(frame, (320, 180))
        cv2.imwrite(f"diag_msmf_{i}.jpg", thumb)
        print(f"    -> Saved diag_msmf_{i}.jpg")
    else:
        print(f"  MSMF [{i}]: {aw}x{ah}@{afps:.0f}fps | FAILED TO READ FRAME")
    cap.release()

print("\nDone. Check diag_msmf_*.jpg files to visually identify each device.")
