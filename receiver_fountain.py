import cv2
import numpy as np
import os
import sys
import struct
import time
import argparse
import hashlib
import zlib
from common import *

# Fountain protocol constants (local to fountain files, not in common.py)
FOUNTAIN_MAGIC = 0xF0C0
FOUNT_HEADER_FMT = '>HIH'   # magic(2) + seed(4) + K(2)
FOUNT_HEADER_PRE_CRC = 8     # struct.calcsize(FOUNT_HEADER_FMT)
FOUNT_CRC_SIZE = 4
FOUNT_HEADER_SIZE = FOUNT_HEADER_PRE_CRC + FOUNT_CRC_SIZE  # 12

# --- PRNG (SplitMix32) Port ---
class PRNG:
    def __init__(self, seed):
        self.a = int(seed) & 0xFFFFFFFF

    def next(self):
        self.a = (self.a | 0)
        self.a = (self.a + 0x9e3779b9) & 0xFFFFFFFF
        t = self.a ^ (self.a >> 16)
        t = (t * 0x21f0aaad) & 0xFFFFFFFF
        t = t ^ (t >> 15)
        t = (t * 0x735a2d97) & 0xFFFFFFFF
        t = t ^ (t >> 15)
        return t & 0xFFFFFFFF

    def next_float(self):
        return self.next() / 4294967296.0

# --- Decoder Logic ---
class FountainDecoder:
    def __init__(self, total_chunks, payload_size):
        self.K = total_chunks
        self.payload_size = payload_size
        self.chunks = {} # Recovered chunks: {index: bytearray}
        self.droplets = [] # List of (indices_set, data_bytearray)
        self.chunk_to_droplets = {} # Map chunk_index -> list of droplet_indices in self.droplets
        
        # Initialize mapping
        for i in range(self.K):
            self.chunk_to_droplets[i] = []

    def add_droplet(self, seed, data):
        # Reconstruct indices from seed
        prng = PRNG(seed)

        # Degree distribution (Must match JS exactly)
        degree = 1
        r = prng.next_float()
        if r < 0.1: degree = 1
        elif r < 0.6: degree = 2
        else: degree = int(prng.next_float() * min(self.K, 20)) + 1

        # FIX: Cap degree to K to prevent infinite loop when degree > K
        degree = min(degree, self.K)

        indices = set()
        while len(indices) < degree:
            idx = prng.next() % self.K
            indices.add(idx)
            
        # Optimization: If we already have some of these chunks, XOR them out immediately
        # This is "Peeling" on the fly
        new_indices = set()
        current_data = bytearray(data)
        
        for idx in indices:
            if idx in self.chunks:
                # We already know this chunk, XOR it out
                chunk_data = self.chunks[idx]
                for i in range(len(current_data)):
                    current_data[i] ^= chunk_data[i]
            else:
                new_indices.add(idx)
        
        if not new_indices:
            return # Redundant droplet, all chunks known
            
        # If reduced to degree 1, we found a new chunk!
        if len(new_indices) == 1:
            found_idx = new_indices.pop()
            self.resolve_chunk(found_idx, current_data)
        else:
            # Store for later
            droplet_entry = [new_indices, current_data]
            self.droplets.append(droplet_entry)
            # Map dependencies
            for idx in new_indices:
                self.chunk_to_droplets[idx].append(droplet_entry)

    def resolve_chunk(self, chunk_idx, chunk_data):
        if chunk_idx in self.chunks:
            return
            
        self.chunks[chunk_idx] = chunk_data
        
        # Propagate to other droplets (Peeling)
        affected_droplets = self.chunk_to_droplets[chunk_idx]
        
        for droplet in affected_droplets:
            indices, data = droplet
            if chunk_idx in indices:
                indices.remove(chunk_idx)
                # XOR data
                for i in range(len(data)):
                    data[i] ^= chunk_data[i]
                
                # Check if it became degree 1
                if len(indices) == 1:
                    next_idx = indices.pop()
                    self.resolve_chunk(next_idx, data)

    def is_complete(self):
        return len(self.chunks) == self.K

    def get_file_data(self):
        out = bytearray()
        for i in range(self.K):
            if i in self.chunks:
                out.extend(self.chunks[i])
            else:
                out.extend(b'\x00' * self.payload_size)
        return out

def parse_fountain_metadata(full_data):
    """Parse fountain metadata prefix from reassembled data.

    New format: [4B file_size][32B SHA-256][2B name_len][NB name][file_content]
    Returns (file_size, sha256_hash, filename, content_offset) or (None, None, None, None).
    """
    if len(full_data) < 38:  # 4 + 32 + 2 minimum
        return None, None, None, None
    try:
        file_size = struct.unpack('>I', full_data[0:4])[0]
        sha256_hash = full_data[4:36]
        name_len = struct.unpack('>H', full_data[36:38])[0]
        if name_len > 1024 or 38 + name_len > len(full_data):
            return None, None, None, None
        filename = full_data[38:38 + name_len].decode('utf-8')
        content_offset = 38 + name_len
        return file_size, sha256_hash, filename, content_offset
    except Exception:
        return None, None, None, None


def sample_frame(frame, offset_x=0, offset_y=0, scale_x=1.0, scale_y=1.0):
    """Samples the center pixel of each block with offset and scaling."""
    if frame.shape[0] != HEIGHT or frame.shape[1] != WIDTH:
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        
    half_block = BLOCK_SIZE // 2
    
    # Calculate sampling coordinates
    # X coordinates: center of each block
    grid_x = np.arange(COLS)
    sample_x = (grid_x * BLOCK_SIZE * scale_x + offset_x + half_block).astype(int)
    
    # Y coordinates
    grid_y = np.arange(ROWS)
    sample_y = (grid_y * BLOCK_SIZE * scale_y + offset_y + half_block).astype(int)
    
    # Clip to bounds to avoid crash
    np.clip(sample_x, 0, WIDTH - 1, out=sample_x)
    np.clip(sample_y, 0, HEIGHT - 1, out=sample_y)
    
    # Advanced indexing to sample
    # frame is (H, W, 3)
    # We want (ROWS, COLS, 3)
    # sample_y is (ROWS,), sample_x is (COLS,)
    # We use broadcasting: frame[sample_y[:, None], sample_x]
    
    sampled = frame[sample_y[:, None], sample_x]
    
    return sampled

def decode_frame_data(sampled_grid):
    """Decodes black/white blocks to bytes."""
    flat = sampled_grid.reshape(-1, 3)
    # Threshold (Green channel is usually good)
    bits = (flat[:, 1] > 128).astype(np.uint8)
    packed = np.packbits(bits)
    return packed.tobytes()

def main():
    parser = argparse.ArgumentParser(description="HDMI Exfiltration Receiver (Fountain)")
    parser.add_argument("source", help="Video source (Camera index or file)")
    parser.add_argument("--output", default="received_files", help="Output directory")
    args = parser.parse_args()
    
    source = args.source
    if source.isdigit(): source = int(source)
    
    cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"Error: Could not open video source {source}")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, 60) 
    
    print(f"Listening on {source}...")
    
    decoder = None
    start_time = None
    
    HEADER_LEN = FOUNT_HEADER_SIZE  # 12 (was 6)
    
    frame_count = 0
    
    offset_x = 0
    offset_y = 0
    scale_x = 1.0
    scale_y = 1.0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame")
            break
            
        # Show frame immediately to verify camera is working
        debug_frame = frame.copy()
        
        # Draw grid with offset and scale
        # Vertical lines
        for c in range(0, COLS, 10):
            x = int(c * BLOCK_SIZE * scale_x) + offset_x
            if 0 <= x < WIDTH:
                cv2.line(debug_frame, (x, 0), (x, HEIGHT), (0, 0, 255), 1)
        
        # Horizontal lines
        for r in range(0, ROWS, 10):
            y = int(r * BLOCK_SIZE * scale_y) + offset_y
            if 0 <= y < HEIGHT:
                cv2.line(debug_frame, (0, y), (WIDTH, y), (0, 0, 255), 1)
        
        # Draw info text
        info = f"Pos: {offset_x},{offset_y} | Scale: {scale_x:.3f},{scale_y:.3f}"
        cv2.putText(debug_frame, info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(debug_frame, "Arrows: Move | W/S: Y-Scale | A/D: X-Scale", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
        cv2.imshow('Receiver Fountain', debug_frame)
        
        key = cv2.waitKey(1)
        if key == 27: break
        
        # Movement
        if key == ord('j'): offset_x -= 1
        elif key == ord('l'): offset_x += 1
        elif key == ord('i'): offset_y -= 1
        elif key == ord('k'): offset_y += 1
        elif key == 2424832: pass # Arrow keys handling if needed
        
        # Scaling (Fine tuning)
        elif key == ord('d'): scale_x += 0.001
        elif key == ord('a'): scale_x -= 0.001
        elif key == ord('w'): scale_y += 0.001
        elif key == ord('s'): scale_y -= 0.001
        
        frame_count += 1
        if frame_count % 60 == 0:
            # Keep alive message
            pass

        try:
            # Pass offsets and scale to sample_frame
            sampled = sample_frame(frame, offset_x, offset_y, scale_x, scale_y)
            raw_bytes = decode_frame_data(sampled)

            # Parse protocol header (12 bytes)
            if len(raw_bytes) < FOUNT_HEADER_SIZE:
                continue

            # Unpack pre-CRC fields: magic(2) + seed(4) + K(2)
            magic, seed, K = struct.unpack(FOUNT_HEADER_FMT,
                raw_bytes[:FOUNT_HEADER_PRE_CRC])

            # Magic number check
            if magic != FOUNTAIN_MAGIC:
                continue

            # Extract stored CRC
            stored_crc = struct.unpack('>I',
                raw_bytes[FOUNT_HEADER_PRE_CRC:FOUNT_HEADER_SIZE])[0]

            payload = raw_bytes[FOUNT_HEADER_SIZE:]

            # Verify CRC32 (over pre-CRC header + payload)
            computed_crc = zlib.crc32(
                raw_bytes[:FOUNT_HEADER_PRE_CRC] + payload) & 0xFFFFFFFF
            if computed_crc != stored_crc:
                continue  # CRC mismatch -- corruption detected

            # Sanity check
            if K == 0 or K > 60000:
                continue
            
            # Initialize decoder on first valid packet
            if decoder is None:
                print(f"\nDetected transmission! K={K} chunks.")
                decoder = FountainDecoder(K, len(payload))
                start_time = time.time()
            
            # Add droplet
            if decoder.K == K: # Ensure consistent session
                decoder.add_droplet(seed, payload)
                
                progress = len(decoder.chunks) / K
                sys.stdout.write(f"\rProgress: {progress:.1%} ({len(decoder.chunks)}/{K})")
                sys.stdout.flush()
                
                if decoder.is_complete():
                    print("\nDownload Complete!")
                    duration = time.time() - start_time
                    full_data = decoder.get_file_data()

                    if not os.path.exists(args.output):
                        os.makedirs(args.output)

                    # Parse enhanced metadata
                    file_size, expected_sha256, filename, content_offset = parse_fountain_metadata(full_data)

                    if file_size is not None and filename is not None:
                        # Extract file content
                        file_content = bytes(full_data[content_offset:content_offset + file_size])

                        # SHA-256 verification
                        actual_sha256 = hashlib.sha256(file_content).digest()
                        if actual_sha256 != expected_sha256:
                            print("ERROR: SHA-256 MISMATCH -- file corrupted!")
                            print(f"  Expected: {expected_sha256.hex()}")
                            print(f"  Actual:   {actual_sha256.hex()}")
                        else:
                            print(f"SHA-256 verified OK.")

                        safe_name = os.path.basename(filename)
                        save_path = os.path.join(args.output, safe_name)
                        print(f"Detected filename: {safe_name} ({file_size} bytes)")
                    else:
                        # Fallback: metadata parsing failed
                        print("Metadata decode failed. Saving raw payload.")
                        file_content = bytes(full_data)
                        fname = f"received_{int(time.time())}.bin"
                        save_path = os.path.join(args.output, fname)

                    with open(save_path, 'wb') as f:
                        f.write(file_content)

                    print(f"Saved to {save_path}")
                    print(f"Time: {duration:.2f}s")
                    total_bytes = len(file_content)
                    speed_mbps = (total_bytes * 8) / duration / 1_000_000 if duration > 0 else 0
                    print(f"Speed: {speed_mbps:.2f} Mbps")
                    break
            else:
                # Debug mismatch
                # print(f"\rIgnored packet with K={K} (Expected {decoder.K})")
                pass
                    
        except Exception as e:
            # print(f"Error: {e}")
            pass
        
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
