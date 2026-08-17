# Method references V1

## Miki porous-material model

Miki, Y. (1990). Acoustical properties of porous materials—Modifications of Delany–Bazley models. *Journal of the Acoustical Society of Japan (E)*, 11(1), 19–24. DOI: [10.1250/ast.11.19](https://doi.org/10.1250/ast.11.19)

本实验按冻结参数实现 Miki 修正的 Delany–Bazley 经验关系，并计算刚性背衬多孔层的法向入射吸声系数。

## Barrier diffraction relation

Kurze, U. J., & Anderson, G. S. (1971). Sound attenuation by barriers. *Applied Acoustics*, 4(1), 35–53. DOI: [10.1016/0003-682X(71)90024-7](https://doi.org/10.1016/0003-682X(71)90024-7)

本实验采用任务中冻结的 Kurze–Anderson 型衍射衰减表达式，作为简化自由场工程筛选指标。

## Finite-length barrier context

Lam, Y. W. (1994). Using Maekawa's chart to calculate finite length barrier insertion loss. *Applied Acoustics*, 42(1), 29–40. DOI: [10.1016/0003-682X(94)90122-8](https://doi.org/10.1016/0003-682X(94)90122-8)

当前 Python 有限屏障实现只借鉴 **minimum diffracted path concept**。它被严格表述为 **a simplified dominant minimum-diffracted-path approximation**，不是 Lam 1994 方法的完整复现；本实现不包含其有限长度屏障模型中的相干相位/压力叠加。

## Method boundary

本文档中的方法仅支持 analytical/semi-empirical acoustic evaluation、simplified free-field acoustic model、theoretical prediction 和 engineering screening calculation。不得将输出描述为 COMSOL、有限元、完整室内声场仿真或实验验证结果。

