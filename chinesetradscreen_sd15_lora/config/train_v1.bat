@echo off
chcp 65001 >nul
cd /d D:\AI\sd-scripts

"D:\app_down\anaconda\envs\sd15_lora\python.exe" -m accelerate.commands.launch ^
  train_network.py ^
  --pretrained_model_name_or_path="D:/AI/models/sd15/v1-5-pruned-emaonly.safetensors" ^
  --dataset_config="E:/Desktop/论文写作/屏风-文化遗产-计算机交叉-张方瑾老师/实验/data/train_v1/dataset_config.toml" ^
  --output_dir="D:/AI/experiments/chinesetradscreen_sd15_lora_v1/models" ^
  --output_name="chinesetradscreen_sd15_lora_v1" ^
  --logging_dir="D:/AI/experiments/chinesetradscreen_sd15_lora_v1/logs" ^
  --log_with="tensorboard" ^
  --save_model_as="safetensors" ^
  --save_precision="fp16" ^
  --network_module="networks.lora" ^
  --network_dim=8 ^
  --network_alpha=8 ^
  --network_train_unet_only ^
  --unet_lr=1e-4 ^
  --optimizer_type="AdamW8bit" ^
  --lr_scheduler="constant" ^
  --max_train_epochs=15 ^
  --save_every_n_epochs=3 ^
  --mixed_precision="fp16" ^
  --gradient_checkpointing ^
  --cache_latents ^
  --sdpa ^
  --gradient_accumulation_steps=1 ^
  --seed=42 ^
  --max_data_loader_n_workers=0

pause
