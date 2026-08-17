from pathlib import Path
from PIL import Image
import csv, subprocess, sys, time, traceback

root = Path(r'D:\AI\experiments\chinesetradscreen_sd15_lora_v1\candidate_generation_e09')
images_root = root / 'images'
config = root / 'config'
manifest = root / 'generation_manifest_e09_240.csv'
python = r'D:\app_down\anaconda\envs\sd15_lora\python.exe'
sd_scripts = Path(r'D:\AI\sd-scripts')
gen_img = sd_scripts / 'gen_img.py'
base_model = r'D:\AI\models\sd15\v1-5-pruned-emaonly.safetensors'
lora = r'D:\AI\experiments\chinesetradscreen_sd15_lora_v1\models\chinesetradscreen_sd15_lora_v1-000009.safetensors'
negative = 'cropped, close-up, incomplete screen, deformed structure, broken frame, duplicated structure, text, watermark, blurry, low quality'
seeds = [42,1234,2026,7,77,314,512,888,1024,2048,4096,6060,8080,10001,13579,22222,31415,42424,54321,65000]
prompts = {
'A1':'chinesetradscreen, traditional Chinese folding screen, multi-panel screen, complete screen, wooden frame, overall frontal view, continuous composition, elegant traditional decorative design',
'A2':'chinesetradscreen, traditional Chinese folding screen, multi-panel screen, complete screen, wooden frame, painted landscape panels, calligraphy accents, overall frontal view, balanced composition',
'A3':'chinesetradscreen, traditional Chinese folding screen, multi-panel screen, complete screen, wooden frame, traditional decorative border, refined painted composition, overall view',
'B1':'chinesetradscreen, modern reinterpretation of a traditional Chinese folding screen, multi-panel screen, complete screen, wooden frame, simplified decorative language, clean lines, overall frontal view',
'B2':'chinesetradscreen, minimalist traditional Chinese folding screen, multi-panel screen, complete screen, elegant wooden frame, reduced ornament, contemporary design expression, overall view',
'B3':'chinesetradscreen, modern decorative folding screen inspired by traditional Chinese screen design, multi-panel screen, complete screen, simplified continuous landscape motif, balanced modern form',
'C1':'chinesetradscreen, contemporary Chinese folding screen, multi-panel screen, complete screen, wooden frame, abstracted mountain-and-water motif, refined composition, overall frontal view',
'C2':'chinesetradscreen, contemporary reinterpretation of a traditional Chinese folding screen, multi-panel screen, complete screen, geometric simplification, rhythmic panel divisions, elegant overall composition',
'C3':'chinesetradscreen, modern Chinese folding screen, multi-panel screen, complete screen, semi-abstract painted composition, elegant panel rhythm, refined decorative design',
'D1':'chinesetradscreen, contemporary folding screen design, multi-panel screen, complete screen, wooden frame, standing in a contemporary interior, elegant presentation, three-quarter angled view',
'D2':'chinesetradscreen, decorative partition screen inspired by traditional Chinese folding screen, multi-panel structure, complete screen, modern interior setting, refined overall composition',
'D3':'chinesetradscreen, modern interior divider inspired by traditional Chinese folding screen, multi-panel screen, complete screen, Chinese traditional visual language, refined contemporary design, angled view',
}
recorded = set()
with manifest.open(encoding='utf-8', newline='') as f:
    for row in csv.DictReader(f): recorded.add(row['image_id'])

def record_ready(pid):
    added = 0
    for seed in seeds:
        image_id = f'{pid}_seed{seed}'
        if image_id in recorded: continue
        path = images_root / pid / f'{image_id}.png'
        if not path.is_file(): continue
        try:
            with Image.open(path) as im:
                info = dict(im.info)
                size = im.size
                im.verify()
            if size != (512,512): raise RuntimeError(f'Wrong size: {path}: {size}')
            expected = {'prompt':prompts[pid],'negative-prompt':negative,'seed':str(seed),'sampler':'euler_a','steps':'30','scale':'7.0'}
            for key,value in expected.items():
                if info.get(key) != value: raise RuntimeError(f'Metadata mismatch {key}: {path}: {info.get(key)!r} != {value!r}')
        except (OSError, EOFError, SyntaxError, ValueError):
            continue
        row=[image_id,pid,seed,prompts[pid],negative,base_model,lora,0.9,512,512,30,7.0,'euler_a','fp16',f'images/{pid}/{image_id}.png']
        with manifest.open('a',encoding='utf-8',newline='') as f: csv.writer(f).writerow(row)
        recorded.add(image_id); added += 1
        print(f'[MANIFEST] recorded {image_id} ({len(recorded)}/240)',flush=True)
    return added

start=time.time()
print('[RUN] Chinese Traditional Folding Screen Candidate Generation E09',flush=True)
print('[PARAMS] checkpoint='+lora,flush=True)
print('[PARAMS] multiplier=0.9; 512x512; steps=30; cfg=7.0; sampler=euler_a; batch=1; fp16; SDPA',flush=True)
print('[PARAMS] seeds='+','.join(map(str,seeds)),flush=True)
try:
    for pid,prompt in prompts.items():
        print(f'\n[STAGE_START] {pid} expected=20',flush=True)
        record_ready(pid)
        existing=sum((images_root/pid/f'{pid}_seed{s}.png').is_file() for s in seeds)
        recorded_stage=sum(f'{pid}_seed{s}' in recorded for s in seeds)
        if existing == 20 and recorded_stage == 20:
            print(f'[STAGE_SKIP] {pid} already complete; no regeneration',flush=True)
            continue
        if existing != 0:
            raise RuntimeError(f'Partial existing stage {pid}: files={existing}, manifest={recorded_stage}; refusing overwrite')
        cmd=[python,str(gen_img),'--v1','--ckpt',base_model,'--outdir',str(images_root),'--from_file',str(config/f'{pid}_prompts_e09.txt'),'--W','512','--H','512','--steps','30','--scale','7.0','--sampler','euler_a','--batch_size','1','--images_per_prompt','1','--fp16','--sdpa','--network_module','networks.lora','--network_weights',lora,'--network_mul','0.9']
        print('[COMMAND] '+subprocess.list2cmdline(cmd),flush=True)
        proc=subprocess.Popen(cmd,cwd=str(sd_scripts))
        while proc.poll() is None:
            record_ready(pid)
            time.sleep(0.5)
        record_ready(pid)
        actual=sum((images_root/pid/f'{pid}_seed{s}.png').is_file() for s in seeds)
        print(f'[STAGE_END] {pid} exit_code={proc.returncode} images={actual} manifest_total={len(recorded)}',flush=True)
        if proc.returncode != 0: raise RuntimeError(f'Generation failed at prompt {pid}, exit code {proc.returncode}')
        if actual != 20: raise RuntimeError(f'Image count mismatch at prompt {pid}: {actual}/20')
    if len(recorded) != 240: raise RuntimeError(f'Manifest count mismatch: {len(recorded)}/240')
    elapsed=time.time()-start
    print(f'[COMPLETED] images=240 manifest=240 duration_seconds={elapsed:.1f}',flush=True)
    with (config/'generation_record_e09_240.txt').open('a',encoding='utf-8') as f:
        f.write(f'\nStatus:\ncompleted\n\nGenerated images:\n240\n\nGeneration duration seconds:\n{elapsed:.1f}\n')
except Exception:
    print('[FAILED]',flush=True)
    traceback.print_exc()
    with (config/'generation_record_e09_240.txt').open('a',encoding='utf-8') as f: f.write(f'\nStatus:\nfailed\n\nGenerated images recorded:\n{len(recorded)}\n')
    sys.exit(1)
