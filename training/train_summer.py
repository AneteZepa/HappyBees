import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import torch.onnx

# ==========================================
# 1. WRAPPER
# ==========================================
class ModelWithScaler(nn.Module):
    def __init__(self, base_model, min_vals, scale_vals, use_softmax=False):
        super(ModelWithScaler, self).__init__()
        self.base_model = base_model
        self.use_softmax = use_softmax
        self.register_buffer('min_val', torch.tensor(min_vals, dtype=torch.float32))
        self.register_buffer('scale_val', torch.tensor(scale_vals, dtype=torch.float32))

    def forward(self, x):
        # Normalize
        x_scaled = (x - self.min_val) / (self.scale_val + 1e-6)
        output = self.base_model(x_scaled)
        if self.use_softmax:
            return torch.softmax(output, dim=1)
        return output

# ==========================================
# 2. ARCHITECTURES
# ==========================================
class SummerCNN(nn.Module):
    def __init__(self, input_features): 
        super(SummerCNN, self).__init__()
        # Increased depth slightly to capture more complex patterns
        self.layer1 = nn.Sequential(nn.Conv1d(1, 16, 3, padding=1), nn.BatchNorm1d(16), nn.ReLU(), nn.MaxPool1d(2))
        self.layer2 = nn.Sequential(nn.Conv1d(16, 32, 3, padding=1), nn.BatchNorm1d(32), nn.ReLU(), nn.MaxPool1d(2))
        self.layer3 = nn.Sequential(nn.Conv1d(32, 64, 3, padding=1), nn.BatchNorm1d(64), nn.ReLU(), nn.MaxPool1d(2))
        
        # Calculate flatten size dynamically based on input
        # Input / 2 / 2 / 2 = Input / 8
        flat_size = 64 * (input_features // 8)
        
        self.fc = nn.Sequential(
            nn.Flatten(), 
            nn.Linear(flat_size, 64), 
            nn.ReLU(), 
            nn.Dropout(0.2), 
            nn.Linear(64, 2)
        )
        
    def forward(self, x):
        x = x.unsqueeze(1) 
        x = self.layer3(self.layer2(self.layer1(x)))
        return self.fc(x)


# ==========================================
# 3. DATA PROCESSING
# ==========================================
def get_summer_data():
    print("☀️ Processing Summer Data...")
    df = pd.read_csv('D1_sensor_data.csv', parse_dates=['published_at'])
    df = df.sort_values(['tag_number', 'published_at'])
    
    # Feature Engineering
    df['hour'] = df['published_at'].dt.hour
    df['is_daytime'] = df['hour'].apply(lambda x: 1 if 6 <= x <= 20 else 0)
    df['rolling_audio'] = df.groupby('tag_number')['audio_density'].transform(lambda x: x.rolling(window=12, min_periods=1).mean())
    df['audio_spike_ratio'] = df['audio_density'] / (df['rolling_audio'] + 1e-6)
    
    piping_freqs = ['hz_335.693359375', 'hz_366.2109375', 'hz_396.728515625', 'hz_427.24609375']
    df['high_freq_power'] = df[piping_freqs].sum(axis=1)
    
    threshold_spike = df['audio_spike_ratio'].quantile(0.95)
    threshold_piping = df['high_freq_power'].quantile(0.95)
    
    conditions = [
        (df['audio_spike_ratio'] > threshold_spike) & (df['is_daytime'] == 1),
        (df['high_freq_power'] > threshold_piping),
        (df['audio_density'] > df['audio_density'].mean()) & (df['is_daytime'] == 0)
    ]
    df['target'] = np.where(np.any(conditions, axis=0), 1, 0)
    
    audio_cols = [c for c in df.columns if 'hz_' in c]
    feature_names = ['temperature', 'humidity', 'hour', 'audio_spike_ratio'] + audio_cols
    df_clean = df.dropna(subset=feature_names)
    
    return df_clean[feature_names].values.astype(np.float32), df_clean['target'].values.astype(np.longlong), len(feature_names)


# ==========================================
# 4. EXPORT ROUTINE
# ==========================================
def bake_and_export():
    # --- SUMMER ---
    X_summer, y_summer, n_feats_summer = get_summer_data()
    min_summer = np.percentile(X_summer, 1, axis=0)
    max_summer = np.percentile(X_summer, 99, axis=0)
    X_summer_clipped = np.clip(X_summer, min_summer, max_summer)
    X_train_scaled = ((X_summer_clipped - min_summer) / (max_summer - min_summer + 1e-6)).astype(np.float32)
    
    cnn = SummerCNN(n_feats_summer)
    
    # Neutral weights, but adding a Scheduler
    criterion = nn.CrossEntropyLoss(weight=torch.tensor([1.0, 1.0])) 
    optimizer = optim.Adam(cnn.parameters(), lr=0.002) # Start slightly higher
    
    # SCHEDULER: Reduce LR by half every 5 epochs
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.5)
    
    print("Training Summer Model (Dynamic LR + Reporting Average Loss)...")
    dataset = TensorDataset(torch.from_numpy(X_train_scaled), torch.from_numpy(y_summer))
    loader = DataLoader(dataset, batch_size=128, shuffle=True) # Larger batch for stability
    
    cnn.train()
    for epoch in range(15):
        epoch_loss = 0.0
        for inputs, labels in loader:
            optimizer.zero_grad()
            loss = criterion(cnn(inputs), labels)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
        
        # Step the scheduler
        scheduler.step()
        
        # Calculate Average Loss
        avg_loss = epoch_loss / len(loader)
        current_lr = scheduler.get_last_lr()[0]
        print(f"Epoch {epoch+1} | Avg Loss: {avg_loss:.5f} | LR: {current_lr:.6f}")
            
    final_summer_model = ModelWithScaler(cnn, min_summer, max_summer, use_softmax=True)
    final_summer_model.eval()
    
    dummy_input_sum = torch.randn(1, n_feats_summer)
    torch.onnx.export(final_summer_model, dummy_input_sum, "summer_bee_smart_v7.onnx", 
                      input_names=['raw_input'], output_names=['probability'])
    print("✅ Saved 'summer_bee_smart_v7.onnx'")

if __name__ == "__main__":
    bake_and_export()