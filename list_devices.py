import cv2

def list_ports():
    print("Scanning for video devices (indices 0-10)...")
    available_ports = []
    # Test ports 0 to 10
    for dev_port in range(10):
        cap = cv2.VideoCapture(dev_port, cv2.CAP_DSHOW) # CAP_DSHOW is often faster/better on Windows
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                print(f"[SUCCESS] Port {dev_port}: Found device (Resolution: {w}x{h})")
                available_ports.append(dev_port)
            else:
                print(f"[WARNING] Port {dev_port}: Device opened but failed to read frame.")
            cap.release()
        # else:
            # print(f"Port {dev_port}: Not found") # Too noisy
    
    if not available_ports:
        print("No working video devices found.")
    else:
        print(f"\nFound {len(available_ports)} device(s). Try using one of these indices.")

if __name__ == '__main__':
    list_ports()
