import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import torch.onnx

# ==========================================
# 1. THE WINTER WRAPPER (Raw -> Scaled -> AE -> Raw)
# ==========================================
class WinterWrapper(nn.Module):
    def __init__(self, base_model, min_vals, scale_vals):
        super(WinterWrapper, self).__init__()
        self.base_model = base_model
        # Register constants so they save inside the ONNX file
        self.register_buffer('min_val', torch.tensor(min_vals, dtype=torch.float32))
        self.register_buffer('scale_val', torch.tensor(scale_vals, dtype=torch.float32))

    def forward(self, x):
        # 1. Scale Down (Normalize to 0-1 for the Neural Net)
        x_scaled = (x - self.min_val) / (self.scale_val + 1e-6)
        
        # 2. Reconstruct (Neural Net predicts in 0-1 range)
        reconstructed_scaled = self.base_model(x_scaled)
        
        # 3. Scale Up (Unscale back to Real World Units)
        # Output = (Scaled * Range) + Min
        return (reconstructed_scaled * (self.scale_val + 1e-6)) + self.min_val

# ==========================================
# 2. MODEL ARCHITECTURE
# ==========================================
class WinterAutoencoder(nn.Module):
    def __init__(self, input_dim):
        super(WinterAutoencoder, self).__init__()
        # Encoder: Compress
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 12), 
            nn.Tanh(), 
            nn.Linear(12, 6), 
            nn.Tanh(), 
            nn.Linear(6, 3)
        )
        # Decoder: Expand
        self.decoder = nn.Sequential(
            nn.Linear(3, 6), 
            nn.Tanh(), 
            nn.Linear(6, 12), 
            nn.Tanh(), 
            nn.Linear(12, input_dim)
        )
    def forward(self, x):
        encoded = self.encoder(x)
        return self.decoder(encoded)

# ==========================================
# 3. DATA LOADING
# ==========================================
def get_winter_data():
    print("❄️ Processing Winter Data...")
    try:
        df = pd.read_csv('D2_sensor_data.csv', parse_dates=['published_at'])
    except FileNotFoundError:
        print("Error: D2_sensor_data.csv not found.")
        exit()
        
    df = df.sort_values(['tag_number', 'published_at'])
    
    # Feature Engineering
    # 1. Stability
    df['temp_stability'] = df.groupby('tag_number')['temperature'].transform(lambda x: x.rolling(window=12).var())
    
    # 2. Heater Audio Power
    heater_freqs = ['hz_183.10546875', 'hz_213.623046875', 'hz_244.140625']
    df['heater_power'] = df[heater_freqs].sum(axis=1)
    
    # 3. Heater Efficiency Ratio
    df['heater_ratio'] = df['heater_power'] / (df['audio_density'] + 1e-6)
    
    features = ['temperature', 'humidity', 'temp_stability', 'heater_power', 'heater_ratio']
    
    # Filter for Healthy Period (Nov 1 - Nov 21)
    train_df = df[df['published_at'] < '2020-11-21'].dropna(subset=features)
    
    print(f"   Training on {len(train_df)} healthy samples.")
    return train_df[features].values.astype(np.float32), len(features)

# ==========================================
# 4. MAIN ROUTINE
# ==========================================
if __name__ == "__main__":
    # A. Get Data
    X_winter, n_feats = get_winter_data()
    
    # B. Calculate Scaling Stats (Robust 1st/99th Percentile)
    # We use these to train, AND we bake them into the wrapper
    min_winter = np.percentile(X_winter, 1, axis=0)
    max_winter = np.percentile(X_winter, 99, axis=0)
    scale_range = max_winter - min_winter
    
    # C. Prepare Training Data (Scaled 0-1)
    X_clipped = np.clip(X_winter, min_winter, max_winter)
    X_scaled = ((X_clipped - min_winter) / (scale_range + 1e-6)).astype(np.float32)
    
    # D. Train the Core Model
    autoencoder = WinterAutoencoder(n_feats)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(autoencoder.parameters(), lr=0.002)
    
    print("   Training Autoencoder...")
    dataset = TensorDataset(torch.from_numpy(X_scaled))
    loader = DataLoader(dataset, batch_size=128, shuffle=True)
    
    autoencoder.train()
    for epoch in range(15):
        epoch_loss = 0.0
        for batch in loader:
            inputs = batch[0]
            optimizer.zero_grad()
            loss = criterion(autoencoder(inputs), inputs)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
        print(f"   Epoch {epoch+1} | Avg Loss: {(epoch_loss/len(loader)):.5f}")

    # E. Bake the Wrapper (The "Unscaler")
    print("   Wrapping and Exporting...")
    final_model = WinterWrapper(autoencoder, min_winter, max_winter)
    final_model.eval()
    
    # F. Export ONNX
    dummy_input = torch.randn(1, n_feats)
    torch.onnx.export(final_model, dummy_input, "winter_bee_anomaly_v8.onnx", 
                      input_names=['raw_input'], 
                      output_names=['reconstructed_raw_output'])
    
    print("✅ Saved 'winter_bee_anomaly_v8.onnx'")
    print("   -> Upload this to Edge Impulse (Input: Other, Output: Freeform/Classification)")