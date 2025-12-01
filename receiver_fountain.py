import cv2
import numpy as np
import os
import sys
import struct
import time
import argparse
from common import *

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

def sample_frame(frame):
    """Samples the center pixel of each block."""
    if frame.shape[0] != HEIGHT or frame.shape[1] != WIDTH:
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        
    half_block = BLOCK_SIZE // 2
    sampled = frame[half_block::BLOCK_SIZE, half_block::BLOCK_SIZE]
    return sampled[:ROWS, :COLS]

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
    
    # Header size in bytes: 6 (Seed: 4, K: 2)
    HEADER_LEN = 6
    
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        sampled = sample_frame(frame)
        raw_bytes = decode_frame_data(sampled)
        
        # Parse Header
        if len(raw_bytes) < HEADER_LEN: continue
        
        try:
            # Seed (4), K (2)
            seed_bytes = raw_bytes[:4]
            k_bytes = raw_bytes[4:6]
            
            seed = struct.unpack('>I', seed_bytes)[0]
            K = struct.unpack('>H', k_bytes)[0]
            
            payload = raw_bytes[HEADER_LEN:]
            
            # Sanity check
            if K == 0 or K > 60000: continue 
            
            # Initialize decoder on first valid packet
            if decoder is None:
                print(f"Detected transmission! K={K} chunks.")
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
                    
                    if not os.path.exists(args.output): os.makedirs(args.output)
                    fname = f"received_{int(time.time())}.bin"
                    path = os.path.join(args.output, fname)
                    
                    with open(path, 'wb') as f:
                        f.write(full_data)
                        
                    print(f"Saved to {path}")
                    print(f"Time: {duration:.2f}s")
                    break
                    
        except Exception as e:
            pass
            
        cv2.imshow('Receiver Fountain', frame)
        if cv2.waitKey(1) == 27: break
        
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
