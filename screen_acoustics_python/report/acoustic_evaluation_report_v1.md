# S12 / S20 Analytical / Semi-empirical Acoustic Performance Evaluation V1

## Material Passport

- Artifact type: Experiment Result
- Verification status: VERIFIED by deterministic re-run checks in `validate_results.py`
- Data provenance: frozen S12 = B2_seed42 and S20 = C2_seed42 mappings
- Research scope: analytical/semi-empirical engineering screening calculation
- Generated: 2026-08-15T15:59:12.836849+08:00

# 1 Research objective

本研究不进行 COMSOL、有限元、FDTD、BEM 或完整室内声场仿真。目标是以理论/半经验方法分别评价统一多孔层的频率相关吸声能力，以及在简化自由场中不同折叠几何的有限屏障衍射遮挡潜力。结果属于 theoretical prediction 与 engineering screening calculation，不是公共空间真实声场的精确预测或实验验证。

# 2 Frozen candidates

- S12 = B2_seed42
- S20 = C2_seed42

IF-VIKOR 输入、评分、排序与候选映射保持冻结，本阶段没有反向修改。

# 3 Engineering translation

| Candidate | Source design | Panels | Panel width (m) | Height (m) | Thickness (m) | Fold angle (deg) | Projected width (m) | Fold depth (m) |
|---|---|---|---|---|---|---|---|---|
| S12 | B2_seed42 | 6 | 0.400000 | 1.800000 | 0.070000 | 30.000000 | 2.318222 | 0.103528 |
| S20 | C2_seed42 | 6 | 0.400000 | 1.800000 | 0.070000 | 12.000000 | 2.386853 | 0.041811 |

声学构造统一为前侧 30 mm 多孔层 + 10 mm 刚性芯层 + 后侧 30 mm 多孔层。上述尺寸均为 **engineering translation assumptions**，不是从生成图像中测量出的真实制造尺寸。保持尺寸与材料完全相同、只改变折叠角，可以减少混杂变量。

# 4 Material model

采用 Miki (1990) modified Delany–Bazley model，时间约定在代码中统一为 `exp(+jωt)`：

```text
X = 1000 f / sigma
Zc = rho0 c0 [1 + 5.50 X^(-0.632) - j 8.43 X^(-0.632)]
kc = (omega/c0) [1 + 7.81 X^(-0.618) - j 11.41 X^(-0.618)]
Zs = -j Zc / tan(kc d)
R = (Zs - rho0 c0) / (Zs + rho0 c0)
alpha = 1 - |R|^2
```

基准参数为 sigma = 12000 Pa·s/m²、d = 0.030 m。吸声系数与屏障衍射 IL 是互补指标，未被相加或合成为未经验证的总分。

# 5 Material absorption results

| Frequency (Hz) | alpha | Aeq one face (m²) | Aeq two faces (m²) |
|---|---|---|---|
| 125 | 0.026921 | 0.116297 | 0.232594 |
| 160 | 0.040056 | 0.173044 | 0.346088 |
| 200 | 0.056745 | 0.245140 | 0.490280 |
| 250 | 0.079624 | 0.343975 | 0.687950 |
| 315 | 0.112022 | 0.483935 | 0.967871 |
| 400 | 0.157855 | 0.681934 | 1.363868 |
| 500 | 0.215374 | 0.930416 | 1.860833 |
| 630 | 0.293618 | 1.268429 | 2.536858 |
| 800 | 0.397523 | 1.717299 | 3.434597 |
| 1000 | 0.515489 | 2.226912 | 4.453825 |

等效吸声面积仅为 `alpha × area` 的补充指标，不是 Sabine 混响时间预测。

# 6 Material sensitivity

仅改变流阻率，厚度保持 0.030 m。10 个频率算术平均 alpha：8000 Pa·s/m² = 0.162182；12000 Pa·s/m² = 0.189523；16000 Pa·s/m² = 0.212284。

# 7 Simplified finite barrier model

对 source–receiver 直线先进行屏扇交点及交点高度判断。无遮挡时 IL = 0 dB。遮挡时，对 6 条顶部屏扇边、6 条底部屏扇边及 2 条外侧竖边共 14 条候选边，最小化：

```text
L(t) = distance(Source, P(t)) + distance(P(t), Receiver), 0 <= t <= 1
L_direct = distance(Source, Receiver)
delta = L_diffracted - L_direct
lambda = c0 / f
N = 2 delta / lambda = 2 f delta / c0
u = sqrt(2 pi N)
IL = 5 + 20 log10[u / tanh(u)]
```

当 N < 1e-12 时采用稳定极限 IL = 5 dB。当前实现称为 **a simplified dominant minimum-diffracted-path approximation**，不是 Lam (1994) 相干相位/压力叠加有限屏障模型的完整复现。

# 8 Source and receivers

| Point | x (m) | y (m) | z (m) |
|---|---|---|---|
| Source | -1.500 | 0.000 | 1.200 |
| R1 | 1.500 | -0.800 | 1.200 |
| R2 | 1.500 | -0.400 | 1.200 |
| R3 | 1.500 | 0.000 | 1.200 |
| R4 | 1.500 | 0.400 | 1.200 |
| R5 | 1.500 | 0.800 | 1.200 |

模型不使用绝对声源声压或声功率，不虚构 SPL。

# 9 S12 / S20 IL results

| Frequency (Hz) | S12 mean IL (dB) | S20 mean IL (dB) | S12 - S20 (dB) |
|---|---|---|---|
| 125 | 7.574895 | 7.573977 | 0.000918 |
| 160 | 8.130142 | 8.129078 | 0.001065 |
| 200 | 8.703699 | 8.702500 | 0.001200 |
| 250 | 9.345196 | 9.343864 | 0.001332 |
| 315 | 10.078360 | 10.076899 | 0.001461 |
| 400 | 10.903675 | 10.902095 | 0.001580 |
| 500 | 11.728686 | 11.727012 | 0.001674 |
| 630 | 12.628708 | 12.626955 | 0.001753 |
| 800 | 13.596946 | 13.595132 | 0.001814 |
| 1000 | 14.526713 | 14.524859 | 0.001854 |

# 10 Receiver variability

以下标准差为固定 5 个接收点集合的总体标准差（ddof = 0）。

| Candidate | Frequency (Hz) | Mean (dB) | Std (dB) | Min (dB) | Max (dB) |
|---|---|---|---|---|---|
| S12 | 125 | 7.574895 | 0.027600 | 7.542264 | 7.609809 |
| S12 | 160 | 8.130142 | 0.032020 | 8.092284 | 8.170635 |
| S12 | 200 | 8.703699 | 0.036085 | 8.661032 | 8.749320 |
| S12 | 250 | 9.345196 | 0.040069 | 9.297815 | 9.395838 |
| S12 | 315 | 10.078360 | 0.043948 | 10.026389 | 10.133888 |
| S12 | 400 | 10.903675 | 0.047534 | 10.847460 | 10.963713 |
| S12 | 500 | 11.728686 | 0.050380 | 11.669102 | 11.792302 |
| S12 | 630 | 12.628708 | 0.052754 | 12.566312 | 12.695305 |
| S12 | 800 | 13.596946 | 0.054593 | 13.532372 | 13.665849 |
| S12 | 1000 | 14.526713 | 0.055798 | 14.460711 | 14.597124 |
| S20 | 125 | 7.573977 | 0.027597 | 7.541099 | 7.607583 |
| S20 | 160 | 8.129078 | 0.032018 | 8.090931 | 8.168056 |
| S20 | 200 | 8.702500 | 0.036085 | 8.659505 | 8.746417 |
| S20 | 250 | 9.343864 | 0.040071 | 9.296118 | 9.392618 |
| S20 | 315 | 10.076899 | 0.043953 | 10.024526 | 10.130361 |
| S20 | 400 | 10.902095 | 0.047541 | 10.845443 | 10.959903 |
| S20 | 500 | 11.727012 | 0.050390 | 11.666962 | 11.788269 |
| S20 | 630 | 12.626955 | 0.052767 | 12.564069 | 12.691085 |
| S20 | 800 | 13.595132 | 0.054609 | 13.530049 | 13.661487 |
| S20 | 1000 | 14.524859 | 0.055815 | 14.458336 | 14.592668 |

# 11 Overall metrics

| candidate | source_design | fold_angle_deg | projected_width_m | fold_depth_m | band_arithmetic_mean_il_db | band_min_il_db | band_max_il_db | overall_mean_il_db | overall_std_il_db |
|---|---|---|---|---|---|---|---|---|---|
| S12 | B2_seed42 | 30.000000 | 2.318222 | 0.103528 | 10.721702 | 7.574895 | 14.526713 | 10.721702 | 2.246081 |
| S20 | C2_seed42 | 12.000000 | 2.386853 | 0.041811 | 10.720237 | 7.573977 | 14.524859 | 10.720237 | 2.245781 |

这些是描述统计，不是 NRC、STC、Rw、DnT 或 sound insulation rating。

# 12 Model validation

- Miki unit test: PASS — 125 Hz = 0.026921, 500 Hz = 0.215374, 1000 Hz = 0.515489；相对冻结参考值绝对差均不超过 0.01。
- Kurze–Anderson mathematical test: PASS — delta = 0.246 m, f = 500 Hz, N = 0.716783217, IL = 11.784887 dB。
- S12 geometry: PASS — 6 panels, 7 vertices, developed width = 2.400000000 m。
- S20 geometry: PASS — 6 panels, 7 vertices, developed width = 2.400000000 m。
- Range checks: PASS — no NaN/Inf; alpha in [0,1]; delta >= 0; all optimizations converged.
- High attenuation warning: None; no predicted IL exceeded 30 dB.

# 13 Interpretation

S12–S20 的全频率平均 IL 差为 0.001465 dB；最大绝对频率差为 0.001854 dB，出现在 1000 Hz。The simplified diffraction model did not predict a substantial acoustic difference between the two folding geometries.

为回答“是否能够清晰区分”，本报告仅采用透明的描述性规则：最大绝对均值差达到 1.0 dB 才标记为 Yes；该规则不是感知阈值或声学标准。当前结果：**No**。

# 14 Scientific limitations

1. No full-wave simulation.
2. No room reflections.
3. No ground reflection.
4. No multiple diffraction.
5. No phase-coherent summation.
6. No scattering prediction.
7. No transmission through panel.
8. Porous absorption and diffraction IL are reported separately.
9. Engineering dimensions are assumed translation parameters.
10. Results are theoretical screening predictions, not laboratory validation.
11. Structural vibration and manufacturing details are not modeled.

# 15 Link to IF-VIKOR

IF-VIKOR 已冻结。本阶段只对 S12 与 S20 做独立声学工程筛选，不重新评分、不重新排序、不向前述决策结果回写。

# 16 Paper-ready Methods paragraph

**English.** An analytical/semi-empirical acoustic evaluation was conducted to screen two frozen IF-VIKOR compromise candidates (S12 and S20) without full-wave or room-acoustic simulation. Both concepts were translated into six-panel screens with identical developed width (2.4 m), height (1.8 m), total thickness (70 mm), and a symmetric 30/10/30 mm porous–rigid-core–porous assembly; only the adjacent turn angle differed (30° for S12 and 12° for S20). Normal-incidence absorption of the 30 mm porous layer was estimated using the Miki modified Delany–Bazley relations. Geometric screening was estimated in a simplified free field using direct-ray blockage testing and a Kurze–Anderson-type attenuation equation applied to the dominant minimum diffracted path among 14 finite candidate edges. Material absorption and diffraction insertion loss were reported as separate, complementary proxies.

**中文。** 本研究采用理论/半经验声学评价，在不进行完整波动或室内声场仿真的条件下，对两个冻结 IF-VIKOR 折衷候选 S12 与 S20 进行工程筛选。两方案均被转译为六扇屏风，展开总宽 2.4 m、高 1.8 m、总厚 70 mm，并采用相同的 30/10/30 mm 多孔层—刚性芯层—多孔层构造；唯一变化为相邻屏扇转向角（S12 为 30°，S20 为 12°）。30 mm 多孔层的法向入射吸声系数采用 Miki 修正 Delany–Bazley 关系估算；几何遮挡能力则在简化自由场中，通过直接声线遮挡判断，并对 14 条有限候选边中的主导最短衍射路径应用 Kurze–Anderson 型衰减公式进行估算。材料吸声与衍射插入损失作为两个独立且互补的指标报告。

# 17 Paper-ready Results paragraph

**English.** The baseline Miki calculation predicted normal-incidence absorption coefficients of 0.027, 0.080, 0.215, and 0.515 at 125, 250, 500, and 1000 Hz, respectively. Across the 125–1000 Hz evaluation band, the mean predicted diffraction insertion losses were 10.722 dB for S12 and 10.720 dB for S20. Their average difference was 0.001465 dB, and the largest frequency-specific difference was 0.001854 dB at 1000 Hz. The simplified analytical/semi-empirical model does not provide strong evidence that folding geometry alone produces a substantial acoustic-performance difference between S12 and S20.

**中文。** Miki 基准计算在 125、250、500 和 1000 Hz 得到的法向入射吸声系数分别为 0.027、0.080、0.215 和 0.515。在 125–1000 Hz 频带内，S12 与 S20 的平均预测衍射插入损失分别为 10.722 dB 和 10.720 dB；两者平均差为 0.001465 dB，最大频率差为 0.001854 dB（1000 Hz）。当前简化模型没有为“仅由折叠几何造成显著声学性能差异”提供强证据。

# 18 Discussion paragraph

S12 与 S20 的预测 IL 曲线非常接近，说明在当前简化模型与冻结声源—接收点配置下，统一材料、屏风高度和总体有限宽度比 30°/12° 的折角差异更占主导。该结果不是实验失败，而是模型边界内的合法科研结果。折叠几何可能造成的散射、多重反射、漫射场相互作用与相干效应未被当前主导最短衍射路径近似捕捉，需要更高阶数值模型或受控实验才能验证。

## Scientific conclusion

The simplified analytical/semi-empirical model does not provide strong evidence that folding geometry alone produces a substantial acoustic-performance difference between S12 and S20.
