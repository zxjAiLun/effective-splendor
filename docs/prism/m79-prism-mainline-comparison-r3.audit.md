# M79 阅读修订 r3：证据与更正

仅离线读取现有结果，0 新对局、0 模型前向。竞技判门、冻结结果、原画像和 r2 均未改写。

## 输入绑定

| 来源 | 文件 | SHA256 |
| --- | --- | --- |
| result | local-artifacts/prism/m79-mainline/completion-r30/harvest/m79-prism-mainline.result.json | 50a76a85fbfef46e41d296efa23915b4f76c4fae0672151e9e6ecd960735f85a |
| profile | docs/prism/m79-prism-mainline-candidate-profile-r37.json | 5483619f4e285c893a8ecbba84d81a9beb3c77210c36a616789c6ce998fd1b92 |
| contract | benchmarks/m79-prism-mainline.execution-plan.json | e16351f17ed8bbcaeb21dcdd3d0b23f39c27aefa0a112101a7b555caa79a8176 |
| previous_reading | docs/prism/m79-prism-mainline-comparison-r2.html | 4d32588122e04c9ee625b05119e16ecc287217e467a19923e2520369b16ad333 |
| original_markdown | docs/prism/m79-prism-mainline-evidence.md | 0b9112f9fa301675039a78aae131800ed2b072bf314b5a49e73751edf86e7d12 |
| delivery | local-artifacts/prism/m79-mainline/completion-r37/delivery-manifest.json | 150a0945ecf6a06c6049a30d43f22e9f9167fdfe25c1ba4f13f20a59ea5dc544 |

## 贵族覆盖更正

原画像 noble_coverage 与“获得贵族局数/总局数”的定义不符。本阅读修订从结果 pairs 中六共同对手的 candidate_metrics.games_with_nobles 求和，再除以3072；双方座位计数加总核对一致。不修改原画像或重判原风格政策。此处只更正描述值。

| 模型 | 旧字段值 | 获得贵族局数 | 分母 | 更正覆盖 |
| --- | --- | --- | --- | --- |
| M79 c20 | 0.001953125 | 888 | 3072 | 28.91% |
| M75 c20 | 0.0016276041666666667 | 899 | 3072 | 29.26% |
| Balance v0.2.0 | 0.005208333333333333 | 1209 | 3072 | 39.36% |

## 检查范围

生成时验证6项输入SHA；23组胜平负、双方互补、座位加总、局数网格；共同池与直接对战及4个单对手端点估计复算；画像样本数、大牌印刷分和首次大牌覆盖复算。置信区间复用原冻结统计，未重新bootstrap或审计全部原始回放。原始完整Markdown保留所有宏观/座位细节。

视觉与交互检查单独记录在 reading-receipt.json；生成文件不代表视觉通过。

## 原统计（完整保留）

```json
{
  "bootstrap": {
    "samples": 20000,
    "seed": 79029999,
    "generator": "PCG64",
    "endpoint_order": [
      "common_delta",
      "direct_parent",
      "latest-alpha",
      "latest-balance",
      "heuristic",
      "released-alpha"
    ],
    "quantile_method": "linear",
    "ordinary_interval": [
      0.025,
      0.975
    ],
    "family_one_sided_lower_quantile": 0.025,
    "common_resampling": "per replicate, each common opponent in declared order; draw paired seed blocks with replacement and average opponent means equally"
  },
  "endpoints": {
    "common_delta": {
      "name": "common_delta",
      "status": "COMPLETE",
      "completeness": {
        "status": "COMPLETE",
        "planned_rows": 6144,
        "observed_rows": 6144,
        "missing_rows": 0,
        "planned_seed_blocks": 1536,
        "complete_paired_seed_blocks": 1536,
        "by_opponent": [
          {
            "opponent": "heuristic",
            "planned_rows": 1024,
            "observed_rows": 1024,
            "missing_rows": 0,
            "planned_seed_blocks": 256,
            "complete_paired_seed_blocks": 256
          },
          {
            "opponent": "general",
            "planned_rows": 1024,
            "observed_rows": 1024,
            "missing_rows": 0,
            "planned_seed_blocks": 256,
            "complete_paired_seed_blocks": 256
          },
          {
            "opponent": "balance",
            "planned_rows": 1024,
            "observed_rows": 1024,
            "missing_rows": 0,
            "planned_seed_blocks": 256,
            "complete_paired_seed_blocks": 256
          },
          {
            "opponent": "alpha",
            "planned_rows": 1024,
            "observed_rows": 1024,
            "missing_rows": 0,
            "planned_seed_blocks": 256,
            "complete_paired_seed_blocks": 256
          },
          {
            "opponent": "beta",
            "planned_rows": 1024,
            "observed_rows": 1024,
            "missing_rows": 0,
            "planned_seed_blocks": 256,
            "complete_paired_seed_blocks": 256
          },
          {
            "opponent": "released-alpha",
            "planned_rows": 1024,
            "observed_rows": 1024,
            "missing_rows": 0,
            "planned_seed_blocks": 256,
            "complete_paired_seed_blocks": 256
          }
        ]
      },
      "estimate": 0.01611328125,
      "interval": {
        "ordinary_95": {
          "lower": -0.0030924479166666665,
          "upper": 0.035319010416666664
        },
        "family_one_sided_lower": -0.0030924479166666665,
        "lower_quantile": 0.025,
        "samples": 20000
      },
      "diagnostic_completed_only": {
        "estimate": 0.01611328125,
        "basis": "complete paired seed blocks only; descriptive and never a formal gate"
      },
      "worst_best_point_bounds": {
        "worst": 0.01611328125,
        "best": 0.01611328125,
        "basis": "missing game half-scores assigned 0/1 after averaging the two seats per seed"
      },
      "gates": {
        "enhancement": "FAIL",
        "retention": "PASS"
      }
    },
    "direct_parent": {
      "name": "direct_parent",
      "status": "COMPLETE",
      "completeness": {
        "status": "COMPLETE",
        "planned_rows": 1024,
        "observed_rows": 1024,
        "missing_rows": 0,
        "planned_seed_blocks": 512,
        "complete_paired_seed_blocks": 512
      },
      "estimate": 0.54345703125,
      "interval": {
        "ordinary_95": {
          "lower": 0.5126953125,
          "upper": 0.57373046875
        },
        "family_one_sided_lower": 0.5126953125,
        "lower_quantile": 0.025,
        "samples": 20000
      },
      "diagnostic_completed_only": {
        "estimate": 0.54345703125,
        "basis": "complete paired seed blocks only; descriptive and never a formal gate"
      },
      "worst_best_point_bounds": {
        "worst": 0.54345703125,
        "best": 0.54345703125,
        "basis": "missing game half-scores assigned 0/1 after averaging the two seats per seed"
      },
      "gates": {
        "enhancement": "PASS",
        "retention": "PASS"
      }
    },
    "latest-alpha": {
      "name": "latest-alpha",
      "status": "COMPLETE",
      "completeness": {
        "status": "COMPLETE",
        "planned_rows": 1024,
        "observed_rows": 1024,
        "missing_rows": 0,
        "planned_seed_blocks": 256,
        "complete_paired_seed_blocks": 256
      },
      "estimate": 0.0458984375,
      "interval": {
        "ordinary_95": {
          "lower": -0.0087890625,
          "upper": 0.1015625
        },
        "family_one_sided_lower": -0.0087890625,
        "lower_quantile": 0.025,
        "samples": 20000
      },
      "diagnostic_completed_only": {
        "estimate": 0.0458984375,
        "basis": "complete paired seed blocks only; descriptive and never a formal gate"
      },
      "worst_best_point_bounds": {
        "worst": 0.0458984375,
        "best": 0.0458984375,
        "basis": "missing game half-scores assigned 0/1 after averaging the two seats per seed"
      },
      "gates": {
        "retention": "PASS"
      }
    },
    "latest-balance": {
      "name": "latest-balance",
      "status": "COMPLETE",
      "completeness": {
        "status": "COMPLETE",
        "planned_rows": 1024,
        "observed_rows": 1024,
        "missing_rows": 0,
        "planned_seed_blocks": 256,
        "complete_paired_seed_blocks": 256
      },
      "estimate": 0.0595703125,
      "interval": {
        "ordinary_95": {
          "lower": 0.009765625,
          "upper": 0.1083984375
        },
        "family_one_sided_lower": 0.009765625,
        "lower_quantile": 0.025,
        "samples": 20000
      },
      "diagnostic_completed_only": {
        "estimate": 0.0595703125,
        "basis": "complete paired seed blocks only; descriptive and never a formal gate"
      },
      "worst_best_point_bounds": {
        "worst": 0.0595703125,
        "best": 0.0595703125,
        "basis": "missing game half-scores assigned 0/1 after averaging the two seats per seed"
      },
      "gates": {
        "retention": "PASS"
      }
    },
    "heuristic": {
      "name": "heuristic",
      "status": "COMPLETE",
      "completeness": {
        "status": "COMPLETE",
        "planned_rows": 1024,
        "observed_rows": 1024,
        "missing_rows": 0,
        "planned_seed_blocks": 256,
        "complete_paired_seed_blocks": 256
      },
      "estimate": -0.0517578125,
      "interval": {
        "ordinary_95": {
          "lower": -0.08791503906249998,
          "upper": -0.015625
        },
        "family_one_sided_lower": -0.08791503906249998,
        "lower_quantile": 0.025,
        "samples": 20000
      },
      "diagnostic_completed_only": {
        "estimate": -0.0517578125,
        "basis": "complete paired seed blocks only; descriptive and never a formal gate"
      },
      "worst_best_point_bounds": {
        "worst": -0.0517578125,
        "best": -0.0517578125,
        "basis": "missing game half-scores assigned 0/1 after averaging the two seats per seed"
      },
      "gates": {
        "retention": "FAIL"
      }
    },
    "released-alpha": {
      "name": "released-alpha",
      "status": "COMPLETE",
      "completeness": {
        "status": "COMPLETE",
        "planned_rows": 1024,
        "observed_rows": 1024,
        "missing_rows": 0,
        "planned_seed_blocks": 256,
        "complete_paired_seed_blocks": 256
      },
      "estimate": 0.0732421875,
      "interval": {
        "ordinary_95": {
          "lower": 0.025390625,
          "upper": 0.12109375
        },
        "family_one_sided_lower": 0.025390625,
        "lower_quantile": 0.025,
        "samples": 20000
      },
      "diagnostic_completed_only": {
        "estimate": 0.0732421875,
        "basis": "complete paired seed blocks only; descriptive and never a formal gate"
      },
      "worst_best_point_bounds": {
        "worst": 0.0732421875,
        "best": 0.0732421875,
        "basis": "missing game half-scores assigned 0/1 after averaging the two seats per seed"
      },
      "gates": {
        "retention": "PASS"
      }
    }
  },
  "mainline_recommendation": {
    "status": "FAIL",
    "eligible": false,
    "failed_endpoints": [
      "common_delta",
      "heuristic"
    ],
    "incomplete_endpoints": [],
    "meaning": "PASS recommends the candidate as the next mainline parent only; it does not authorize release, default replacement, or deployment"
  }
}
```
