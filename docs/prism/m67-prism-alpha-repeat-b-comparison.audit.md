# M67 B：Prism Alpha v0.1.5 的独立训练重复 — Agent audit

# M67 原始结果与 Agent 审计

双方greedy；训练采样不参与竞技验收；两臂/不同种子cohort不合并。
四项单侧同时检验：family α=.05，每项下界分位=.0125；20,000 bootstrap；普通区间=.025/.975。
先按seed平均双座，再对六共同对手等权；共同对手检验是候选减父代。
保留门使用≥，增强使用严格>。重复增强要求两臂各自共同对手与直接父代增强全通过。
不足表示未排除容忍外退步或未证实增益，不自动证明模型退化。两个训练种子不证明总体稳健性。
父代 Prism Alpha v0.1.5；fresh AdamW/RNG、outcome-only；每臂5120局/20轮，与M66预算不同；最终c20未发布。

| 臂/检验 | 保留阈值 | 增强阈值 | 估计 | 普通95%区间 | 同时单侧下界 | 保留通过 | 增强通过 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| candidate-a/strength_pool | -0.05 | >0.0 | 0.0763694054776219 | [0.0684869739478958, 0.08430193720774883] | 0.06725116900467602 | True | True |
| candidate-a/direct_parent | 0.45 | >0.5 | 0.6049 | [0.59555, 0.6142] | 0.5942 | True | True |
| candidate-b/strength_pool | -0.05 | >0.0 | 0.06315 | [0.055316666666666674, 0.07091666666666667] | 0.054183125000000006 | True | True |
| candidate-b/direct_parent | 0.45 | >0.5 | 0.57925 | [0.56995, 0.5887] | 0.56855 | True | True |

```json
{
  "format": "m67-prism-fixed-greedy-result-v1",
  "status": "COMPLETED_FIXED_GREEDY_EVALUATION",
  "games": 109995,
  "games_dispatched": 0,
  "action_mode": "both-greedy",
  "candidate_sha256": {
    "base": "3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12",
    "candidate-a": "db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5",
    "candidate-b": "e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4"
  },
  "acceptance_policy": {
    "action_seed": 67020001,
    "bootstrap_samples": 20000,
    "bootstrap_seed": 67029999,
    "common_games_per_model": 30000,
    "common_opponents": [
      "heuristic",
      "initial",
      "general",
      "balance",
      "alpha",
      "beta"
    ],
    "common_seed_end": 9832499,
    "common_seed_start": 9830000,
    "cpu_seconds_per_arena": 72000,
    "direct_games": 10000,
    "direct_seed_end": 9844999,
    "direct_seed_start": 9840000,
    "enhancement_thresholds": {
      "candidate/direct_parent": 0.5,
      "candidate/strength_pool": 0.0
    },
    "family_alpha": 0.05,
    "gates": {
      "candidate/direct_parent": 0.45,
      "candidate/strength_pool": -0.05
    },
    "lower_quantile": 0.0125,
    "memory_bytes": 8589934592,
    "mode": "both-greedy",
    "repeat_success": "both arms clear adjusted enhancement lower bounds for strength pool and direct parent",
    "selection": "no extension or arm/checkpoint selection",
    "statistical_unit": "paired two-seat seed block; six equal-weight common opponents; four gates across two arms",
    "storage_bytes_per_arena": 8589934592,
    "style": "descriptive observed route; no style veto",
    "total_games": 110000,
    "wall_seconds_per_arena": 18000,
    "workers": 4
  },
  "measurements": {
    "candidate-a/strength_pool": {
      "mean": 0.0763694054776219,
      "ci95": [
        0.0684869739478958,
        0.08430193720774883
      ],
      "simultaneous_one_sided_lower": 0.06725116900467602,
      "seed_blocks": 2495,
      "bootstrap_seed": 67029999,
      "bootstrap_samples": 20000,
      "lower_quantile": 0.0125,
      "incomplete_seeds": 5,
      "retained_gaps": 5
    },
    "candidate-a/direct_parent": {
      "mean": 0.6049,
      "ci95": [
        0.59555,
        0.6142
      ],
      "simultaneous_one_sided_lower": 0.5942,
      "seed_blocks": 5000,
      "bootstrap_seed": 67029999,
      "bootstrap_samples": 20000,
      "lower_quantile": 0.0125
    },
    "candidate-b/strength_pool": {
      "mean": 0.06315,
      "ci95": [
        0.055316666666666674,
        0.07091666666666667
      ],
      "simultaneous_one_sided_lower": 0.054183125000000006,
      "seed_blocks": 2500,
      "bootstrap_seed": 67029999,
      "bootstrap_samples": 20000,
      "lower_quantile": 0.0125
    },
    "candidate-b/direct_parent": {
      "mean": 0.57925,
      "ci95": [
        0.56995,
        0.5887
      ],
      "simultaneous_one_sided_lower": 0.56855,
      "seed_blocks": 5000,
      "bootstrap_seed": 67029999,
      "bootstrap_samples": 20000,
      "lower_quantile": 0.0125
    }
  },
  "gates": {
    "candidate-a/strength_pool": true,
    "candidate-a/direct_parent": true,
    "candidate-b/strength_pool": true,
    "candidate-b/direct_parent": true
  },
  "enhancements": {
    "candidate-a/strength_pool": true,
    "candidate-a/direct_parent": true,
    "candidate-b/strength_pool": true,
    "candidate-b/direct_parent": true
  },
  "repeated_efficacy": false,
  "verdicts": {
    "repeated_efficacy": "NOT_CONFIRMED",
    "competitive_retention": {
      "a": "DESCRIPTIVE_PASS_WITH_RETAINED_GAPS",
      "b": "PASS"
    },
    "overall_enhancement": {
      "a": "DESCRIPTIVE_EVIDENCE_WITH_RETAINED_GAPS",
      "b": "CONFIRMED"
    },
    "style": "OBSERVED_PROFILE_NOT_A_VETO",
    "population_robustness": "NOT_ESTABLISHED",
    "same_budget_m66_repeat": false,
    "published": false,
    "default_replaced": false,
    "retained_gaps_count": 5
  },
  "source_config_sha256": "cf98d10153b5a3a5c08f78c0fd000e94f53d8d553b70de710183234f35c3659c",
  "numeric_source_identity": "ce1bb93c9ce5e13bad1ef05845ba531cb3a0366e2de331fec9917ca211ab7303",
  "training_arms": {
    "a": {
      "blueprint": "benchmarks/m67-prism-alpha-repeat-a.train.json",
      "blueprint_identity": "c67c054a6afdfb5444d11b9181b524e2c59fb352feb78d8ee1375b28dd38c835",
      "cycles": 20,
      "games": 5120,
      "run_seed": 67010001,
      "seed_start": 9801000
    },
    "b": {
      "blueprint": "benchmarks/m67-prism-alpha-repeat-b.train.json",
      "blueprint_identity": "69a37b10943e1ff97fca5fb92df718dbdc3fdc4c15e50f7255f9ccca2a40f738",
      "cycles": 20,
      "games": 5120,
      "run_seed": 67010002,
      "seed_start": 9811000
    }
  },
  "training_audits": {
    "a": {
      "path": "audits/a/audit.json",
      "sha256": "c81194410c27ab082d9b6b966eaf6ceb239e262b601abf12d5547466d8859998",
      "audit": {
        "automatic_retries": 0,
        "checkpoint": {
          "changed_from_parent": true,
          "commit": "a24e26e19fbfe20ca45a7c398eca44e3a274b3aac9764f62a4511f1dbdc99276",
          "cycle": 20,
          "exact_export_tensors": 32,
          "games": 5120,
          "global_step": 1065,
          "initialization": {
            "exact_parent_tensors": 32,
            "optimizer_slots": 0,
            "parent_sha256": "3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12",
            "run_seed": 67010001,
            "status": "PASS",
            "torch_rng_sha256": "1cdba5298186a2c739ffd2f41f2b63bca4a8aaff99a9adc44acc5af5b6b2f1c3"
          },
          "new_training_updates": 0,
          "optimizer_slots": 32,
          "run_identity": "952ba7f835f75b3a4b92778fbffbeb4cadfc29ba1d0c7d56ac205f5f98f204af",
          "status": "PASS",
          "update_attempts": 1066,
          "weights_sha256": "db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5"
        },
        "completed_games": 5120,
        "continuation": {
          "adapter_sha256": "1b52ce6277b51b0d2da4b0f7c7dcd9b3ae37728b8617da7a67f771397c5803ff",
          "original_failed_pipeline_retained": true,
          "policy_path": "continuation-r2/policy.json",
          "policy_sha256": "99beb4350d82e2b3cb223a48cdc01f2c93083e38565635d7db015debb49bd1ac",
          "r1_adapter_sha256": "27315290a290ecfaae067bd6de07c83f91edf11a5c289b2f0cd894004441b07d",
          "resource_storage_override": true,
          "resource_wall_override": true,
          "resume_verification": {
            "completed_games": 4007,
            "ledger_commit": "3abb1eb70d13d1aa86b18e48ba76091cb94d6410d683ab23cb58c399e3f451fc",
            "ledger_state_sha256": "db25ab7fa481e2d9fdeccb73adcc463caf1cd9939d2d3c3128ffb5261a8b0b64",
            "new_games": 0,
            "new_updates": 0,
            "run_commit": "ad171c20a29a118ca21396c539411958f93d2e4e646858ec71efe7518c4479d7",
            "state": {
              "model": "5d0cec04c6db88fae07c931128089207d854fde01ae5183c8f5610ba7c2579f4",
              "optimizer": "3a3373cfea72d28ba640ce1487e7eab149f1a35364be88d87a5a8961e35aacf4",
              "progress": "cc155339ef37c561b4863273eb2b876f69a8848305692b237e413e2f8298bf35",
              "rng": "1d9d1fb2d4f4063f995fed3fbb9de895f762e24154807c0593b794e50e15bcdf"
            },
            "status": "PASS_EXACT_FULL_STATE_SAME_HOST_RESUME"
          }
        },
        "new_games": 0,
        "new_optimizer_updates": 0,
        "parity": {
          "atol": 0.0001,
          "max_abs_error": 0.00010562500000332875,
          "rows": 68,
          "rtol": 0.0001,
          "status": "PASS",
          "weights_sha256": "db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5"
        },
        "rule_replay_validation": "all 5120 saved replays via pinned s4_batch_metrics",
        "source_ledger_sha256": "ae3e9ccf38972dc11f49f891a46a84e05ac116a866e0dca03d00273a84398b3d",
        "status": "PASS_TRAINING_ARTIFACT_AUDIT",
        "training_report_sha256": "240a8d002b930c0292996062e7ec08505c1d03f665578231ec8e9899bc57098a",
        "weights_sha256": "db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5"
      }
    },
    "b": {
      "path": "audits/b/audit.json",
      "sha256": "3cb6720271d2f0485a8cb562cdd8bfbd8b546390046fa01c8e147b4d8692b9de",
      "audit": {
        "automatic_retries": 0,
        "checkpoint": {
          "changed_from_parent": true,
          "commit": "ee6fc013bdbb601f3b3a581359b48a5e51fd1de3f7a273dd6171e45b1ff00b84",
          "cycle": 20,
          "exact_export_tensors": 32,
          "games": 5120,
          "global_step": 1086,
          "initialization": {
            "exact_parent_tensors": 32,
            "optimizer_slots": 0,
            "parent_sha256": "3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12",
            "run_seed": 67010002,
            "status": "PASS",
            "torch_rng_sha256": "2aa3628ba6a8d66b75ccbf949fa77462f8d1b1d115b6ff09bd40b20ea64def7c"
          },
          "new_training_updates": 0,
          "optimizer_slots": 32,
          "run_identity": "cb117b7d0bd27178902779649bf422851db28baed78fb985ce94d67bd01a488f",
          "status": "PASS",
          "update_attempts": 1086,
          "weights_sha256": "e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4"
        },
        "completed_games": 5120,
        "continuation": {
          "adapter_sha256": "1b52ce6277b51b0d2da4b0f7c7dcd9b3ae37728b8617da7a67f771397c5803ff",
          "original_failed_pipeline_retained": true,
          "policy_path": "continuation-r2/policy.json",
          "policy_sha256": "99beb4350d82e2b3cb223a48cdc01f2c93083e38565635d7db015debb49bd1ac",
          "r1_adapter_sha256": "27315290a290ecfaae067bd6de07c83f91edf11a5c289b2f0cd894004441b07d",
          "resource_storage_override": true,
          "resource_wall_override": true,
          "resume_verification": null
        },
        "new_games": 0,
        "new_optimizer_updates": 0,
        "parity": {
          "atol": 0.0001,
          "max_abs_error": 0.00013329345702572937,
          "rows": 68,
          "rtol": 0.0001,
          "status": "PASS",
          "weights_sha256": "e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4"
        },
        "rule_replay_validation": "all 5120 saved replays via pinned s4_batch_metrics",
        "source_ledger_sha256": "f6ee50238a32c55da5a76b2ade0ff5e548d3229f27a41b560ecc39c3941244a0",
        "status": "PASS_TRAINING_ARTIFACT_AUDIT",
        "training_report_sha256": "ba536aa47b6e48a5e2a226c3028a86b707b976f451d91733ef8113fe8a9abc9e",
        "weights_sha256": "e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4"
      }
    }
  },
  "sources": [
    {
      "stage": "common",
      "label": "独立共同对手对照",
      "result": "evaluation/reference/result.json",
      "sha256": "c213072d0e4006f9fe0539bcfb050ba8f7b3635a77c98e662f56c0f0d16cd8b0",
      "plan": "evaluation/reference/plan.json",
      "plan_sha256": "4c6421167789273faab74ba6d4e09c230e30a4f86a2b602e4fd495a14dfeaeac",
      "config": "evaluation/reference/config.json",
      "config_sha256": "0aaf4f76dce4c086ab6e95b3570cd3702fe22a060c479a97fa104fe2baba1ccf",
      "completion": "evaluation/reference/completion.json",
      "completion_sha256": "2060d079f03a36c27b06a8b6d5093249d02367f2dbe79b82470d4455650eef1c"
    },
    {
      "stage": "common",
      "label": "独立共同对手对照",
      "result": "evaluation/a-common-recovery-r3/result.json",
      "sha256": "402585a544d988ecf4a0dfdeedb8483cb61e3f93270a5bce0e9e06973ce25796",
      "plan": "evaluation/a-common-recovery-r3/plan.json",
      "plan_sha256": "06a62fdf9a084acb6c21fea1d9f31d4d2494ccf209706506f716c4614adf8d6b",
      "config": "evaluation/a-common-recovery-r3/config.json",
      "config_sha256": "0cb3882934c39c8f6bf76c7a4584c1a2fcd467f9c31097a8f76f812ebb9d755a",
      "completion": "evaluation/a-common-recovery-r3/completion.json",
      "completion_sha256": "9989510369ac2948b406717e70bfc581ee2678a5d398e6994da98c00c0f510b9"
    },
    {
      "stage": "common",
      "label": "独立共同对手对照",
      "result": "evaluation/b-common/result.json",
      "sha256": "8924cc02715330cab085eb88a5f97f96f909ef0856ea4e8cb0d1bf92f004a71e",
      "plan": "evaluation/b-common/plan.json",
      "plan_sha256": "4fdda24703777b009954b11a7e078c40358a7ea36c7b48c7a9b2697d5fa97668",
      "config": "evaluation/b-common/config.json",
      "config_sha256": "c89d92f50b0c460ce3e92847b8fcc81dae3603b507c0079e11a425a089735775",
      "completion": "evaluation/b-common/completion.json",
      "completion_sha256": "efb5a14e11fc0fdd3b054c285c823706725fd2d6689de36deef35dcbcb38ad13"
    },
    {
      "stage": "direct",
      "label": "独立直接起点对照",
      "result": "evaluation/a-direct/result.json",
      "sha256": "6dd998a080405624d7e65744208d7ad2621df08fcd752281ec8fbdabc0a0aa37",
      "plan": "evaluation/a-direct/plan.json",
      "plan_sha256": "f7ad2c5df84e0c350daa63e868a099366fbd084d896d69ecf8c7716ee89ab09e",
      "config": "evaluation/a-direct/config.json",
      "config_sha256": "ec9807ae2f24df70a831e206748f951a710d768b45abb548c300276ac824aae7",
      "completion": "evaluation/a-direct/completion.json",
      "completion_sha256": "aaf217a21eda917cc6c24171e97d1b325ec7d5b31b38dc85140198c64c17b945"
    },
    {
      "stage": "direct",
      "label": "独立直接起点对照",
      "result": "evaluation/b-direct/result.json",
      "sha256": "90ec31751cb444a4b65ad0e4604397b22e4a3640e521d2b1d49f5c3eae612a77",
      "plan": "evaluation/b-direct/plan.json",
      "plan_sha256": "5a94e91185a9d3fbbcee2c861fe4d6977b50be85b61ce6ce18690a741a004eb4",
      "config": "evaluation/b-direct/config.json",
      "config_sha256": "3f124956a6ead97f966d184a8d3ccf078d082e4542d0853814f2a10ee8d7ac2f",
      "completion": "evaluation/b-direct/completion.json",
      "completion_sha256": "a32b6c0e52b3dc7662187b6cd5f15cd72370f26648c72cafb5966597b81fe513"
    }
  ],
  "arena_observations": {
    "reference": {
      "clock_scope": "standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download",
      "limits": {
        "automatic_game_retries": 0,
        "cpu_seconds": 72000.0,
        "expiry_margin_minutes": 45,
        "instance_deadline": null,
        "instance_hours": null,
        "library_threads_per_worker": 1,
        "memory_bytes": 8589934592,
        "storage_bytes": 8589934592,
        "wall_seconds": 18000.0,
        "workers": 4
      },
      "profile": {
        "affinity_cpus": 4,
        "cgroup_constraints": [
          {
            "path": "/sys/fs/cgroup"
          },
          {
            "cgroup_version": 1,
            "memory_max_bytes": 17179869184,
            "path": "/sys/fs/cgroup/memory"
          },
          {
            "cgroup_version": 1,
            "cpu_quota_cores": 4.0,
            "path": "/sys/fs/cgroup/cpu,cpuacct"
          }
        ],
        "effective_cpu_capacity": 4.0,
        "effective_memory_bytes": 16482029568,
        "effective_whole_cores": 4,
        "host_available_memory_bytes": 14804942848,
        "limit_scope": "observed process-tree soft limits; shared platform cgroups are not owned",
        "logical_host_cpus": 4,
        "platform": "linux",
        "recommended_workers": 3
      },
      "resources": {
        "observed_processes": 1,
        "peak_observed_rss_bytes": 6812053504,
        "process_tree_cpu_seconds": 18975.12,
        "process_tree_rss_sum_bytes": 35295232,
        "scope": "sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages"
      },
      "elapsed_wall_seconds": 5994.426990879001
    },
    "a-common": {
      "clock_scope": "standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download",
      "limits": {
        "automatic_game_retries": 0,
        "cpu_seconds": 72000.0,
        "expiry_margin_minutes": 45,
        "instance_deadline": null,
        "instance_hours": null,
        "library_threads_per_worker": 1,
        "memory_bytes": 8589934592,
        "storage_bytes": 8589934592,
        "wall_seconds": 18000.0,
        "workers": 4
      },
      "profile": {
        "affinity_cpus": 4,
        "cgroup_constraints": [
          {
            "path": "/sys/fs/cgroup"
          },
          {
            "cgroup_version": 1,
            "memory_max_bytes": 17179869184,
            "path": "/sys/fs/cgroup/memory"
          },
          {
            "cgroup_version": 1,
            "cpu_quota_cores": 4.0,
            "path": "/sys/fs/cgroup/cpu,cpuacct"
          }
        ],
        "effective_cpu_capacity": 4.0,
        "effective_memory_bytes": 16482029568,
        "effective_whole_cores": 4,
        "host_available_memory_bytes": 14563713024,
        "limit_scope": "observed process-tree soft limits; shared platform cgroups are not owned",
        "logical_host_cpus": 4,
        "platform": "linux",
        "recommended_workers": 3
      },
      "resources": null,
      "elapsed_wall_seconds": 0
    },
    "b-common": {
      "clock_scope": "standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download",
      "limits": {
        "automatic_game_retries": 0,
        "cpu_seconds": 72000.0,
        "expiry_margin_minutes": 45,
        "instance_deadline": null,
        "instance_hours": null,
        "library_threads_per_worker": 1,
        "memory_bytes": 8589934592,
        "storage_bytes": 8589934592,
        "wall_seconds": 18000.0,
        "workers": 4
      },
      "profile": {
        "affinity_cpus": 4,
        "cgroup_constraints": [
          {
            "path": "/sys/fs/cgroup"
          },
          {
            "cgroup_version": 1,
            "memory_max_bytes": 17179869184,
            "path": "/sys/fs/cgroup/memory"
          },
          {
            "cgroup_version": 1,
            "cpu_quota_cores": 4.0,
            "path": "/sys/fs/cgroup/cpu,cpuacct"
          }
        ],
        "effective_cpu_capacity": 4.0,
        "effective_memory_bytes": 16482025472,
        "effective_whole_cores": 4,
        "host_available_memory_bytes": 15026798592,
        "limit_scope": "observed process-tree soft limits; shared platform cgroups are not owned",
        "logical_host_cpus": 4,
        "platform": "linux",
        "recommended_workers": 3
      },
      "resources": {
        "observed_processes": 1,
        "peak_observed_rss_bytes": 247513088,
        "process_tree_cpu_seconds": 19211.010000000002,
        "process_tree_rss_sum_bytes": 35987456,
        "scope": "sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages"
      },
      "elapsed_wall_seconds": 6824.789229767999
    },
    "a-direct": {
      "clock_scope": "standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download",
      "limits": {
        "automatic_game_retries": 0,
        "cpu_seconds": 72000.0,
        "expiry_margin_minutes": 45,
        "instance_deadline": null,
        "instance_hours": null,
        "library_threads_per_worker": 1,
        "memory_bytes": 8589934592,
        "storage_bytes": 8589934592,
        "wall_seconds": 18000.0,
        "workers": 4
      },
      "profile": {
        "affinity_cpus": 4,
        "cgroup_constraints": [
          {
            "path": "/sys/fs/cgroup"
          },
          {
            "cgroup_version": 1,
            "memory_max_bytes": 17179869184,
            "path": "/sys/fs/cgroup/memory"
          },
          {
            "cgroup_version": 1,
            "cpu_quota_cores": 4.0,
            "path": "/sys/fs/cgroup/cpu,cpuacct"
          }
        ],
        "effective_cpu_capacity": 4.0,
        "effective_memory_bytes": 16482025472,
        "effective_whole_cores": 4,
        "host_available_memory_bytes": 15080861696,
        "limit_scope": "observed process-tree soft limits; shared platform cgroups are not owned",
        "logical_host_cpus": 4,
        "platform": "linux",
        "recommended_workers": 3
      },
      "resources": {
        "observed_processes": 1,
        "peak_observed_rss_bytes": 5169270784,
        "process_tree_cpu_seconds": 6541.74,
        "process_tree_rss_sum_bytes": 31809536,
        "scope": "sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages"
      },
      "elapsed_wall_seconds": 2173.012894456
    },
    "b-direct": {
      "clock_scope": "standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download",
      "limits": {
        "automatic_game_retries": 0,
        "cpu_seconds": 72000.0,
        "expiry_margin_minutes": 45,
        "instance_deadline": null,
        "instance_hours": null,
        "library_threads_per_worker": 1,
        "memory_bytes": 8589934592,
        "storage_bytes": 8589934592,
        "wall_seconds": 18000.0,
        "workers": 4
      },
      "profile": {
        "affinity_cpus": 4,
        "cgroup_constraints": [
          {
            "path": "/sys/fs/cgroup"
          },
          {
            "cgroup_version": 1,
            "memory_max_bytes": 17179869184,
            "path": "/sys/fs/cgroup/memory"
          },
          {
            "cgroup_version": 1,
            "cpu_quota_cores": 4.0,
            "path": "/sys/fs/cgroup/cpu,cpuacct"
          }
        ],
        "effective_cpu_capacity": 4.0,
        "effective_memory_bytes": 16482025472,
        "effective_whole_cores": 4,
        "host_available_memory_bytes": 15005016064,
        "limit_scope": "observed process-tree soft limits; shared platform cgroups are not owned",
        "logical_host_cpus": 4,
        "platform": "linux",
        "recommended_workers": 3
      },
      "resources": {
        "observed_processes": 1,
        "peak_observed_rss_bytes": 236310528,
        "process_tree_cpu_seconds": 6557.79,
        "process_tree_rss_sum_bytes": 31846400,
        "scope": "sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages"
      },
      "elapsed_wall_seconds": 2371.4397100469996
    }
  },
  "names": {
    "alpha": "Prism Alpha v0.1.4",
    "balance": "Prism Balance v0.1.0",
    "beta": "Prism Beta v0.1.0",
    "candidate": "M66 final c4 unpublished training checkpoint",
    "candidate-a": "M67种子A最终c20未发布训练检查点",
    "candidate-b": "M67种子B最终c20未发布训练检查点",
    "general": "Prism v0.1.1",
    "heuristic": "Heuristic v0.3.1",
    "initial": "Prism v0.1.0",
    "parent": "Prism Alpha v0.1.5",
    "base": "Prism Alpha v0.1.5"
  },
  "source_result_sha256": [
    "c213072d0e4006f9fe0539bcfb050ba8f7b3635a77c98e662f56c0f0d16cd8b0",
    "402585a544d988ecf4a0dfdeedb8483cb61e3f93270a5bce0e9e06973ce25796",
    "8924cc02715330cab085eb88a5f97f96f909ef0856ea4e8cb0d1bf92f004a71e",
    "6dd998a080405624d7e65744208d7ad2621df08fcd752281ec8fbdabc0a0aa37",
    "90ec31751cb444a4b65ad0e4604397b22e4a3640e521d2b1d49f5c3eae612a77"
  ]
}
```

# reference 原始完整报告

# Prism 通用对战结果（DSW / SSH）



**产物：已完成全部固定网格，Rust规则回放验核与双方指标守恒通过。**



**竞技：DEVELOPMENT_ONLY_NOT_PROMOTED。**这是独立通用开发测量，没有执行任何里程碑正式晋级门。



**风格：描述性数据。**不凭单一更高/更低经济指标授予风格身份。



候选按用户声明的完整模型名及导出SHA识别，未发布检查点仍须在名称中明确标注。每对手恰好双座种子块；个人表按模型身份归并，物理P0不总是候选。



## 候选匹配比较



只有一个候选，匹配基线到候选比较NOT_APPLICABLE。

↑/↓仅为方向标记，不表示更好或差异显著。下面CI为逐对手描述性双座bootstrap；不做多门验收或发布。若只有一个种子块，CI退化，不能据此确认稳定性。



## 总体执行与来源



| 字段 | 记录 |
| --- | --- |
| 固定局数 | 30000 |
| 并发进程 / 每进程库线程 | 4 / 1 |
| 累计已测活动墙钟秒（至报告前监测点） | 5879.6295 |
| 首次派发至报告生成秒（包含暂停） | 5992.9156 |
| 时钟范围 | standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download |
| 资源监控 | observed process-tree soft limits; shared platform cgroups are not owned |
| 已测负载 | {'observed_processes': 2, 'peak_observed_rss_bytes': 238776320, 'process_tree_cpu_seconds': 18769.95, 'process_tree_rss_sum_bytes': 42582016, 'scope': 'sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages'} |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |
| 配置SHA256 | 0aaf4f76dce4c086ab6e95b3570cd3702fe22a060c479a97fa104fe2baba1ccf |
| plan SHA256 | 4c6421167789273faab74ba6d4e09c230e30a4f86a2b602e4fd495a14dfeaeac |
| engine SHA256 | 6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f |
| metrics SHA256 | 39c630d5e0a9e0611ca4ec8c8b2e4a78817bf971c7bdc7446b614035aedbcb37 |
| Git基线 / 源码dirty | NOT_AVAILABLE / None |
| Bootstrap | {'kind': 'descriptive paired seed blocks, not acceptance', 'samples': 20000, 'seed': 64049999} |
| 种子 | [9830000, 9830001, 9830002, 9830003, 9830004, 9830005, 9830006, 9830007, 9830008, 9830009, 9830010, 9830011, 9830012, 9830013, 9830014, 9830015, 9830016, 9830017, 9830018, 9830019, 9830020, 9830021, 9830022, 9830023, 9830024, 9830025, 9830026, 9830027, 9830028, 9830029, 9830030, 9830031, 9830032, 9830033, 9830034, 9830035, 9830036, 9830037, 9830038, 9830039, 9830040, 9830041, 9830042, 9830043, 9830044, 9830045, 9830046, 9830047, 9830048, 9830049, 9830050, 9830051, 9830052, 9830053, 9830054, 9830055, 9830056, 9830057, 9830058, 9830059, 9830060, 9830061, 9830062, 9830063, 9830064, 9830065, 9830066, 9830067, 9830068, 9830069, 9830070, 9830071, 9830072, 9830073, 9830074, 9830075, 9830076, 9830077, 9830078, 9830079, 9830080, 9830081, 9830082, 9830083, 9830084, 9830085, 9830086, 9830087, 9830088, 9830089, 9830090, 9830091, 9830092, 9830093, 9830094, 9830095, 9830096, 9830097, 9830098, 9830099, 9830100, 9830101, 9830102, 9830103, 9830104, 9830105, 9830106, 9830107, 9830108, 9830109, 9830110, 9830111, 9830112, 9830113, 9830114, 9830115, 9830116, 9830117, 9830118, 9830119, 9830120, 9830121, 9830122, 9830123, 9830124, 9830125, 9830126, 9830127, 9830128, 9830129, 9830130, 9830131, 9830132, 9830133, 9830134, 9830135, 9830136, 9830137, 9830138, 9830139, 9830140, 9830141, 9830142, 9830143, 9830144, 9830145, 9830146, 9830147, 9830148, 9830149, 9830150, 9830151, 9830152, 9830153, 9830154, 9830155, 9830156, 9830157, 9830158, 9830159, 9830160, 9830161, 9830162, 9830163, 9830164, 9830165, 9830166, 9830167, 9830168, 9830169, 9830170, 9830171, 9830172, 9830173, 9830174, 9830175, 9830176, 9830177, 9830178, 9830179, 9830180, 9830181, 9830182, 9830183, 9830184, 9830185, 9830186, 9830187, 9830188, 9830189, 9830190, 9830191, 9830192, 9830193, 9830194, 9830195, 9830196, 9830197, 9830198, 9830199, 9830200, 9830201, 9830202, 9830203, 9830204, 9830205, 9830206, 9830207, 9830208, 9830209, 9830210, 9830211, 9830212, 9830213, 9830214, 9830215, 9830216, 9830217, 9830218, 9830219, 9830220, 9830221, 9830222, 9830223, 9830224, 9830225, 9830226, 9830227, 9830228, 9830229, 9830230, 9830231, 9830232, 9830233, 9830234, 9830235, 9830236, 9830237, 9830238, 9830239, 9830240, 9830241, 9830242, 9830243, 9830244, 9830245, 9830246, 9830247, 9830248, 9830249, 9830250, 9830251, 9830252, 9830253, 9830254, 9830255, 9830256, 9830257, 9830258, 9830259, 9830260, 9830261, 9830262, 9830263, 9830264, 9830265, 9830266, 9830267, 9830268, 9830269, 9830270, 9830271, 9830272, 9830273, 9830274, 9830275, 9830276, 9830277, 9830278, 9830279, 9830280, 9830281, 9830282, 9830283, 9830284, 9830285, 9830286, 9830287, 9830288, 9830289, 9830290, 9830291, 9830292, 9830293, 9830294, 9830295, 9830296, 9830297, 9830298, 9830299, 9830300, 9830301, 9830302, 9830303, 9830304, 9830305, 9830306, 9830307, 9830308, 9830309, 9830310, 9830311, 9830312, 9830313, 9830314, 9830315, 9830316, 9830317, 9830318, 9830319, 9830320, 9830321, 9830322, 9830323, 9830324, 9830325, 9830326, 9830327, 9830328, 9830329, 9830330, 9830331, 9830332, 9830333, 9830334, 9830335, 9830336, 9830337, 9830338, 9830339, 9830340, 9830341, 9830342, 9830343, 9830344, 9830345, 9830346, 9830347, 9830348, 9830349, 9830350, 9830351, 9830352, 9830353, 9830354, 9830355, 9830356, 9830357, 9830358, 9830359, 9830360, 9830361, 9830362, 9830363, 9830364, 9830365, 9830366, 9830367, 9830368, 9830369, 9830370, 9830371, 9830372, 9830373, 9830374, 9830375, 9830376, 9830377, 9830378, 9830379, 9830380, 9830381, 9830382, 9830383, 9830384, 9830385, 9830386, 9830387, 9830388, 9830389, 9830390, 9830391, 9830392, 9830393, 9830394, 9830395, 9830396, 9830397, 9830398, 9830399, 9830400, 9830401, 9830402, 9830403, 9830404, 9830405, 9830406, 9830407, 9830408, 9830409, 9830410, 9830411, 9830412, 9830413, 9830414, 9830415, 9830416, 9830417, 9830418, 9830419, 9830420, 9830421, 9830422, 9830423, 9830424, 9830425, 9830426, 9830427, 9830428, 9830429, 9830430, 9830431, 9830432, 9830433, 9830434, 9830435, 9830436, 9830437, 9830438, 9830439, 9830440, 9830441, 9830442, 9830443, 9830444, 9830445, 9830446, 9830447, 9830448, 9830449, 9830450, 9830451, 9830452, 9830453, 9830454, 9830455, 9830456, 9830457, 9830458, 9830459, 9830460, 9830461, 9830462, 9830463, 9830464, 9830465, 9830466, 9830467, 9830468, 9830469, 9830470, 9830471, 9830472, 9830473, 9830474, 9830475, 9830476, 9830477, 9830478, 9830479, 9830480, 9830481, 9830482, 9830483, 9830484, 9830485, 9830486, 9830487, 9830488, 9830489, 9830490, 9830491, 9830492, 9830493, 9830494, 9830495, 9830496, 9830497, 9830498, 9830499, 9830500, 9830501, 9830502, 9830503, 9830504, 9830505, 9830506, 9830507, 9830508, 9830509, 9830510, 9830511, 9830512, 9830513, 9830514, 9830515, 9830516, 9830517, 9830518, 9830519, 9830520, 9830521, 9830522, 9830523, 9830524, 9830525, 9830526, 9830527, 9830528, 9830529, 9830530, 9830531, 9830532, 9830533, 9830534, 9830535, 9830536, 9830537, 9830538, 9830539, 9830540, 9830541, 9830542, 9830543, 9830544, 9830545, 9830546, 9830547, 9830548, 9830549, 9830550, 9830551, 9830552, 9830553, 9830554, 9830555, 9830556, 9830557, 9830558, 9830559, 9830560, 9830561, 9830562, 9830563, 9830564, 9830565, 9830566, 9830567, 9830568, 9830569, 9830570, 9830571, 9830572, 9830573, 9830574, 9830575, 9830576, 9830577, 9830578, 9830579, 9830580, 9830581, 9830582, 9830583, 9830584, 9830585, 9830586, 9830587, 9830588, 9830589, 9830590, 9830591, 9830592, 9830593, 9830594, 9830595, 9830596, 9830597, 9830598, 9830599, 9830600, 9830601, 9830602, 9830603, 9830604, 9830605, 9830606, 9830607, 9830608, 9830609, 9830610, 9830611, 9830612, 9830613, 9830614, 9830615, 9830616, 9830617, 9830618, 9830619, 9830620, 9830621, 9830622, 9830623, 9830624, 9830625, 9830626, 9830627, 9830628, 9830629, 9830630, 9830631, 9830632, 9830633, 9830634, 9830635, 9830636, 9830637, 9830638, 9830639, 9830640, 9830641, 9830642, 9830643, 9830644, 9830645, 9830646, 9830647, 9830648, 9830649, 9830650, 9830651, 9830652, 9830653, 9830654, 9830655, 9830656, 9830657, 9830658, 9830659, 9830660, 9830661, 9830662, 9830663, 9830664, 9830665, 9830666, 9830667, 9830668, 9830669, 9830670, 9830671, 9830672, 9830673, 9830674, 9830675, 9830676, 9830677, 9830678, 9830679, 9830680, 9830681, 9830682, 9830683, 9830684, 9830685, 9830686, 9830687, 9830688, 9830689, 9830690, 9830691, 9830692, 9830693, 9830694, 9830695, 9830696, 9830697, 9830698, 9830699, 9830700, 9830701, 9830702, 9830703, 9830704, 9830705, 9830706, 9830707, 9830708, 9830709, 9830710, 9830711, 9830712, 9830713, 9830714, 9830715, 9830716, 9830717, 9830718, 9830719, 9830720, 9830721, 9830722, 9830723, 9830724, 9830725, 9830726, 9830727, 9830728, 9830729, 9830730, 9830731, 9830732, 9830733, 9830734, 9830735, 9830736, 9830737, 9830738, 9830739, 9830740, 9830741, 9830742, 9830743, 9830744, 9830745, 9830746, 9830747, 9830748, 9830749, 9830750, 9830751, 9830752, 9830753, 9830754, 9830755, 9830756, 9830757, 9830758, 9830759, 9830760, 9830761, 9830762, 9830763, 9830764, 9830765, 9830766, 9830767, 9830768, 9830769, 9830770, 9830771, 9830772, 9830773, 9830774, 9830775, 9830776, 9830777, 9830778, 9830779, 9830780, 9830781, 9830782, 9830783, 9830784, 9830785, 9830786, 9830787, 9830788, 9830789, 9830790, 9830791, 9830792, 9830793, 9830794, 9830795, 9830796, 9830797, 9830798, 9830799, 9830800, 9830801, 9830802, 9830803, 9830804, 9830805, 9830806, 9830807, 9830808, 9830809, 9830810, 9830811, 9830812, 9830813, 9830814, 9830815, 9830816, 9830817, 9830818, 9830819, 9830820, 9830821, 9830822, 9830823, 9830824, 9830825, 9830826, 9830827, 9830828, 9830829, 9830830, 9830831, 9830832, 9830833, 9830834, 9830835, 9830836, 9830837, 9830838, 9830839, 9830840, 9830841, 9830842, 9830843, 9830844, 9830845, 9830846, 9830847, 9830848, 9830849, 9830850, 9830851, 9830852, 9830853, 9830854, 9830855, 9830856, 9830857, 9830858, 9830859, 9830860, 9830861, 9830862, 9830863, 9830864, 9830865, 9830866, 9830867, 9830868, 9830869, 9830870, 9830871, 9830872, 9830873, 9830874, 9830875, 9830876, 9830877, 9830878, 9830879, 9830880, 9830881, 9830882, 9830883, 9830884, 9830885, 9830886, 9830887, 9830888, 9830889, 9830890, 9830891, 9830892, 9830893, 9830894, 9830895, 9830896, 9830897, 9830898, 9830899, 9830900, 9830901, 9830902, 9830903, 9830904, 9830905, 9830906, 9830907, 9830908, 9830909, 9830910, 9830911, 9830912, 9830913, 9830914, 9830915, 9830916, 9830917, 9830918, 9830919, 9830920, 9830921, 9830922, 9830923, 9830924, 9830925, 9830926, 9830927, 9830928, 9830929, 9830930, 9830931, 9830932, 9830933, 9830934, 9830935, 9830936, 9830937, 9830938, 9830939, 9830940, 9830941, 9830942, 9830943, 9830944, 9830945, 9830946, 9830947, 9830948, 9830949, 9830950, 9830951, 9830952, 9830953, 9830954, 9830955, 9830956, 9830957, 9830958, 9830959, 9830960, 9830961, 9830962, 9830963, 9830964, 9830965, 9830966, 9830967, 9830968, 9830969, 9830970, 9830971, 9830972, 9830973, 9830974, 9830975, 9830976, 9830977, 9830978, 9830979, 9830980, 9830981, 9830982, 9830983, 9830984, 9830985, 9830986, 9830987, 9830988, 9830989, 9830990, 9830991, 9830992, 9830993, 9830994, 9830995, 9830996, 9830997, 9830998, 9830999, 9831000, 9831001, 9831002, 9831003, 9831004, 9831005, 9831006, 9831007, 9831008, 9831009, 9831010, 9831011, 9831012, 9831013, 9831014, 9831015, 9831016, 9831017, 9831018, 9831019, 9831020, 9831021, 9831022, 9831023, 9831024, 9831025, 9831026, 9831027, 9831028, 9831029, 9831030, 9831031, 9831032, 9831033, 9831034, 9831035, 9831036, 9831037, 9831038, 9831039, 9831040, 9831041, 9831042, 9831043, 9831044, 9831045, 9831046, 9831047, 9831048, 9831049, 9831050, 9831051, 9831052, 9831053, 9831054, 9831055, 9831056, 9831057, 9831058, 9831059, 9831060, 9831061, 9831062, 9831063, 9831064, 9831065, 9831066, 9831067, 9831068, 9831069, 9831070, 9831071, 9831072, 9831073, 9831074, 9831075, 9831076, 9831077, 9831078, 9831079, 9831080, 9831081, 9831082, 9831083, 9831084, 9831085, 9831086, 9831087, 9831088, 9831089, 9831090, 9831091, 9831092, 9831093, 9831094, 9831095, 9831096, 9831097, 9831098, 9831099, 9831100, 9831101, 9831102, 9831103, 9831104, 9831105, 9831106, 9831107, 9831108, 9831109, 9831110, 9831111, 9831112, 9831113, 9831114, 9831115, 9831116, 9831117, 9831118, 9831119, 9831120, 9831121, 9831122, 9831123, 9831124, 9831125, 9831126, 9831127, 9831128, 9831129, 9831130, 9831131, 9831132, 9831133, 9831134, 9831135, 9831136, 9831137, 9831138, 9831139, 9831140, 9831141, 9831142, 9831143, 9831144, 9831145, 9831146, 9831147, 9831148, 9831149, 9831150, 9831151, 9831152, 9831153, 9831154, 9831155, 9831156, 9831157, 9831158, 9831159, 9831160, 9831161, 9831162, 9831163, 9831164, 9831165, 9831166, 9831167, 9831168, 9831169, 9831170, 9831171, 9831172, 9831173, 9831174, 9831175, 9831176, 9831177, 9831178, 9831179, 9831180, 9831181, 9831182, 9831183, 9831184, 9831185, 9831186, 9831187, 9831188, 9831189, 9831190, 9831191, 9831192, 9831193, 9831194, 9831195, 9831196, 9831197, 9831198, 9831199, 9831200, 9831201, 9831202, 9831203, 9831204, 9831205, 9831206, 9831207, 9831208, 9831209, 9831210, 9831211, 9831212, 9831213, 9831214, 9831215, 9831216, 9831217, 9831218, 9831219, 9831220, 9831221, 9831222, 9831223, 9831224, 9831225, 9831226, 9831227, 9831228, 9831229, 9831230, 9831231, 9831232, 9831233, 9831234, 9831235, 9831236, 9831237, 9831238, 9831239, 9831240, 9831241, 9831242, 9831243, 9831244, 9831245, 9831246, 9831247, 9831248, 9831249, 9831250, 9831251, 9831252, 9831253, 9831254, 9831255, 9831256, 9831257, 9831258, 9831259, 9831260, 9831261, 9831262, 9831263, 9831264, 9831265, 9831266, 9831267, 9831268, 9831269, 9831270, 9831271, 9831272, 9831273, 9831274, 9831275, 9831276, 9831277, 9831278, 9831279, 9831280, 9831281, 9831282, 9831283, 9831284, 9831285, 9831286, 9831287, 9831288, 9831289, 9831290, 9831291, 9831292, 9831293, 9831294, 9831295, 9831296, 9831297, 9831298, 9831299, 9831300, 9831301, 9831302, 9831303, 9831304, 9831305, 9831306, 9831307, 9831308, 9831309, 9831310, 9831311, 9831312, 9831313, 9831314, 9831315, 9831316, 9831317, 9831318, 9831319, 9831320, 9831321, 9831322, 9831323, 9831324, 9831325, 9831326, 9831327, 9831328, 9831329, 9831330, 9831331, 9831332, 9831333, 9831334, 9831335, 9831336, 9831337, 9831338, 9831339, 9831340, 9831341, 9831342, 9831343, 9831344, 9831345, 9831346, 9831347, 9831348, 9831349, 9831350, 9831351, 9831352, 9831353, 9831354, 9831355, 9831356, 9831357, 9831358, 9831359, 9831360, 9831361, 9831362, 9831363, 9831364, 9831365, 9831366, 9831367, 9831368, 9831369, 9831370, 9831371, 9831372, 9831373, 9831374, 9831375, 9831376, 9831377, 9831378, 9831379, 9831380, 9831381, 9831382, 9831383, 9831384, 9831385, 9831386, 9831387, 9831388, 9831389, 9831390, 9831391, 9831392, 9831393, 9831394, 9831395, 9831396, 9831397, 9831398, 9831399, 9831400, 9831401, 9831402, 9831403, 9831404, 9831405, 9831406, 9831407, 9831408, 9831409, 9831410, 9831411, 9831412, 9831413, 9831414, 9831415, 9831416, 9831417, 9831418, 9831419, 9831420, 9831421, 9831422, 9831423, 9831424, 9831425, 9831426, 9831427, 9831428, 9831429, 9831430, 9831431, 9831432, 9831433, 9831434, 9831435, 9831436, 9831437, 9831438, 9831439, 9831440, 9831441, 9831442, 9831443, 9831444, 9831445, 9831446, 9831447, 9831448, 9831449, 9831450, 9831451, 9831452, 9831453, 9831454, 9831455, 9831456, 9831457, 9831458, 9831459, 9831460, 9831461, 9831462, 9831463, 9831464, 9831465, 9831466, 9831467, 9831468, 9831469, 9831470, 9831471, 9831472, 9831473, 9831474, 9831475, 9831476, 9831477, 9831478, 9831479, 9831480, 9831481, 9831482, 9831483, 9831484, 9831485, 9831486, 9831487, 9831488, 9831489, 9831490, 9831491, 9831492, 9831493, 9831494, 9831495, 9831496, 9831497, 9831498, 9831499, 9831500, 9831501, 9831502, 9831503, 9831504, 9831505, 9831506, 9831507, 9831508, 9831509, 9831510, 9831511, 9831512, 9831513, 9831514, 9831515, 9831516, 9831517, 9831518, 9831519, 9831520, 9831521, 9831522, 9831523, 9831524, 9831525, 9831526, 9831527, 9831528, 9831529, 9831530, 9831531, 9831532, 9831533, 9831534, 9831535, 9831536, 9831537, 9831538, 9831539, 9831540, 9831541, 9831542, 9831543, 9831544, 9831545, 9831546, 9831547, 9831548, 9831549, 9831550, 9831551, 9831552, 9831553, 9831554, 9831555, 9831556, 9831557, 9831558, 9831559, 9831560, 9831561, 9831562, 9831563, 9831564, 9831565, 9831566, 9831567, 9831568, 9831569, 9831570, 9831571, 9831572, 9831573, 9831574, 9831575, 9831576, 9831577, 9831578, 9831579, 9831580, 9831581, 9831582, 9831583, 9831584, 9831585, 9831586, 9831587, 9831588, 9831589, 9831590, 9831591, 9831592, 9831593, 9831594, 9831595, 9831596, 9831597, 9831598, 9831599, 9831600, 9831601, 9831602, 9831603, 9831604, 9831605, 9831606, 9831607, 9831608, 9831609, 9831610, 9831611, 9831612, 9831613, 9831614, 9831615, 9831616, 9831617, 9831618, 9831619, 9831620, 9831621, 9831622, 9831623, 9831624, 9831625, 9831626, 9831627, 9831628, 9831629, 9831630, 9831631, 9831632, 9831633, 9831634, 9831635, 9831636, 9831637, 9831638, 9831639, 9831640, 9831641, 9831642, 9831643, 9831644, 9831645, 9831646, 9831647, 9831648, 9831649, 9831650, 9831651, 9831652, 9831653, 9831654, 9831655, 9831656, 9831657, 9831658, 9831659, 9831660, 9831661, 9831662, 9831663, 9831664, 9831665, 9831666, 9831667, 9831668, 9831669, 9831670, 9831671, 9831672, 9831673, 9831674, 9831675, 9831676, 9831677, 9831678, 9831679, 9831680, 9831681, 9831682, 9831683, 9831684, 9831685, 9831686, 9831687, 9831688, 9831689, 9831690, 9831691, 9831692, 9831693, 9831694, 9831695, 9831696, 9831697, 9831698, 9831699, 9831700, 9831701, 9831702, 9831703, 9831704, 9831705, 9831706, 9831707, 9831708, 9831709, 9831710, 9831711, 9831712, 9831713, 9831714, 9831715, 9831716, 9831717, 9831718, 9831719, 9831720, 9831721, 9831722, 9831723, 9831724, 9831725, 9831726, 9831727, 9831728, 9831729, 9831730, 9831731, 9831732, 9831733, 9831734, 9831735, 9831736, 9831737, 9831738, 9831739, 9831740, 9831741, 9831742, 9831743, 9831744, 9831745, 9831746, 9831747, 9831748, 9831749, 9831750, 9831751, 9831752, 9831753, 9831754, 9831755, 9831756, 9831757, 9831758, 9831759, 9831760, 9831761, 9831762, 9831763, 9831764, 9831765, 9831766, 9831767, 9831768, 9831769, 9831770, 9831771, 9831772, 9831773, 9831774, 9831775, 9831776, 9831777, 9831778, 9831779, 9831780, 9831781, 9831782, 9831783, 9831784, 9831785, 9831786, 9831787, 9831788, 9831789, 9831790, 9831791, 9831792, 9831793, 9831794, 9831795, 9831796, 9831797, 9831798, 9831799, 9831800, 9831801, 9831802, 9831803, 9831804, 9831805, 9831806, 9831807, 9831808, 9831809, 9831810, 9831811, 9831812, 9831813, 9831814, 9831815, 9831816, 9831817, 9831818, 9831819, 9831820, 9831821, 9831822, 9831823, 9831824, 9831825, 9831826, 9831827, 9831828, 9831829, 9831830, 9831831, 9831832, 9831833, 9831834, 9831835, 9831836, 9831837, 9831838, 9831839, 9831840, 9831841, 9831842, 9831843, 9831844, 9831845, 9831846, 9831847, 9831848, 9831849, 9831850, 9831851, 9831852, 9831853, 9831854, 9831855, 9831856, 9831857, 9831858, 9831859, 9831860, 9831861, 9831862, 9831863, 9831864, 9831865, 9831866, 9831867, 9831868, 9831869, 9831870, 9831871, 9831872, 9831873, 9831874, 9831875, 9831876, 9831877, 9831878, 9831879, 9831880, 9831881, 9831882, 9831883, 9831884, 9831885, 9831886, 9831887, 9831888, 9831889, 9831890, 9831891, 9831892, 9831893, 9831894, 9831895, 9831896, 9831897, 9831898, 9831899, 9831900, 9831901, 9831902, 9831903, 9831904, 9831905, 9831906, 9831907, 9831908, 9831909, 9831910, 9831911, 9831912, 9831913, 9831914, 9831915, 9831916, 9831917, 9831918, 9831919, 9831920, 9831921, 9831922, 9831923, 9831924, 9831925, 9831926, 9831927, 9831928, 9831929, 9831930, 9831931, 9831932, 9831933, 9831934, 9831935, 9831936, 9831937, 9831938, 9831939, 9831940, 9831941, 9831942, 9831943, 9831944, 9831945, 9831946, 9831947, 9831948, 9831949, 9831950, 9831951, 9831952, 9831953, 9831954, 9831955, 9831956, 9831957, 9831958, 9831959, 9831960, 9831961, 9831962, 9831963, 9831964, 9831965, 9831966, 9831967, 9831968, 9831969, 9831970, 9831971, 9831972, 9831973, 9831974, 9831975, 9831976, 9831977, 9831978, 9831979, 9831980, 9831981, 9831982, 9831983, 9831984, 9831985, 9831986, 9831987, 9831988, 9831989, 9831990, 9831991, 9831992, 9831993, 9831994, 9831995, 9831996, 9831997, 9831998, 9831999, 9832000, 9832001, 9832002, 9832003, 9832004, 9832005, 9832006, 9832007, 9832008, 9832009, 9832010, 9832011, 9832012, 9832013, 9832014, 9832015, 9832016, 9832017, 9832018, 9832019, 9832020, 9832021, 9832022, 9832023, 9832024, 9832025, 9832026, 9832027, 9832028, 9832029, 9832030, 9832031, 9832032, 9832033, 9832034, 9832035, 9832036, 9832037, 9832038, 9832039, 9832040, 9832041, 9832042, 9832043, 9832044, 9832045, 9832046, 9832047, 9832048, 9832049, 9832050, 9832051, 9832052, 9832053, 9832054, 9832055, 9832056, 9832057, 9832058, 9832059, 9832060, 9832061, 9832062, 9832063, 9832064, 9832065, 9832066, 9832067, 9832068, 9832069, 9832070, 9832071, 9832072, 9832073, 9832074, 9832075, 9832076, 9832077, 9832078, 9832079, 9832080, 9832081, 9832082, 9832083, 9832084, 9832085, 9832086, 9832087, 9832088, 9832089, 9832090, 9832091, 9832092, 9832093, 9832094, 9832095, 9832096, 9832097, 9832098, 9832099, 9832100, 9832101, 9832102, 9832103, 9832104, 9832105, 9832106, 9832107, 9832108, 9832109, 9832110, 9832111, 9832112, 9832113, 9832114, 9832115, 9832116, 9832117, 9832118, 9832119, 9832120, 9832121, 9832122, 9832123, 9832124, 9832125, 9832126, 9832127, 9832128, 9832129, 9832130, 9832131, 9832132, 9832133, 9832134, 9832135, 9832136, 9832137, 9832138, 9832139, 9832140, 9832141, 9832142, 9832143, 9832144, 9832145, 9832146, 9832147, 9832148, 9832149, 9832150, 9832151, 9832152, 9832153, 9832154, 9832155, 9832156, 9832157, 9832158, 9832159, 9832160, 9832161, 9832162, 9832163, 9832164, 9832165, 9832166, 9832167, 9832168, 9832169, 9832170, 9832171, 9832172, 9832173, 9832174, 9832175, 9832176, 9832177, 9832178, 9832179, 9832180, 9832181, 9832182, 9832183, 9832184, 9832185, 9832186, 9832187, 9832188, 9832189, 9832190, 9832191, 9832192, 9832193, 9832194, 9832195, 9832196, 9832197, 9832198, 9832199, 9832200, 9832201, 9832202, 9832203, 9832204, 9832205, 9832206, 9832207, 9832208, 9832209, 9832210, 9832211, 9832212, 9832213, 9832214, 9832215, 9832216, 9832217, 9832218, 9832219, 9832220, 9832221, 9832222, 9832223, 9832224, 9832225, 9832226, 9832227, 9832228, 9832229, 9832230, 9832231, 9832232, 9832233, 9832234, 9832235, 9832236, 9832237, 9832238, 9832239, 9832240, 9832241, 9832242, 9832243, 9832244, 9832245, 9832246, 9832247, 9832248, 9832249, 9832250, 9832251, 9832252, 9832253, 9832254, 9832255, 9832256, 9832257, 9832258, 9832259, 9832260, 9832261, 9832262, 9832263, 9832264, 9832265, 9832266, 9832267, 9832268, 9832269, 9832270, 9832271, 9832272, 9832273, 9832274, 9832275, 9832276, 9832277, 9832278, 9832279, 9832280, 9832281, 9832282, 9832283, 9832284, 9832285, 9832286, 9832287, 9832288, 9832289, 9832290, 9832291, 9832292, 9832293, 9832294, 9832295, 9832296, 9832297, 9832298, 9832299, 9832300, 9832301, 9832302, 9832303, 9832304, 9832305, 9832306, 9832307, 9832308, 9832309, 9832310, 9832311, 9832312, 9832313, 9832314, 9832315, 9832316, 9832317, 9832318, 9832319, 9832320, 9832321, 9832322, 9832323, 9832324, 9832325, 9832326, 9832327, 9832328, 9832329, 9832330, 9832331, 9832332, 9832333, 9832334, 9832335, 9832336, 9832337, 9832338, 9832339, 9832340, 9832341, 9832342, 9832343, 9832344, 9832345, 9832346, 9832347, 9832348, 9832349, 9832350, 9832351, 9832352, 9832353, 9832354, 9832355, 9832356, 9832357, 9832358, 9832359, 9832360, 9832361, 9832362, 9832363, 9832364, 9832365, 9832366, 9832367, 9832368, 9832369, 9832370, 9832371, 9832372, 9832373, 9832374, 9832375, 9832376, 9832377, 9832378, 9832379, 9832380, 9832381, 9832382, 9832383, 9832384, 9832385, 9832386, 9832387, 9832388, 9832389, 9832390, 9832391, 9832392, 9832393, 9832394, 9832395, 9832396, 9832397, 9832398, 9832399, 9832400, 9832401, 9832402, 9832403, 9832404, 9832405, 9832406, 9832407, 9832408, 9832409, 9832410, 9832411, 9832412, 9832413, 9832414, 9832415, 9832416, 9832417, 9832418, 9832419, 9832420, 9832421, 9832422, 9832423, 9832424, 9832425, 9832426, 9832427, 9832428, 9832429, 9832430, 9832431, 9832432, 9832433, 9832434, 9832435, 9832436, 9832437, 9832438, 9832439, 9832440, 9832441, 9832442, 9832443, 9832444, 9832445, 9832446, 9832447, 9832448, 9832449, 9832450, 9832451, 9832452, 9832453, 9832454, 9832455, 9832456, 9832457, 9832458, 9832459, 9832460, 9832461, 9832462, 9832463, 9832464, 9832465, 9832466, 9832467, 9832468, 9832469, 9832470, 9832471, 9832472, 9832473, 9832474, 9832475, 9832476, 9832477, 9832478, 9832479, 9832480, 9832481, 9832482, 9832483, 9832484, 9832485, 9832486, 9832487, 9832488, 9832489, 9832490, 9832491, 9832492, 9832493, 9832494, 9832495, 9832496, 9832497, 9832498, 9832499] |
| 完整逐局来源 | source-ledger.json |
| 冻结源码SHA | {'scripts/prism_cloud_storage_snapshot.py': 'b417e62c6aa2ce56ad2968ab0ac4c952b4a954514128a6923efc272129f5eb8c', 'scripts/prism_dsw_arena.py': '172b6f9edbb69b2d0fc139cd3ac4678d5f0392f97b59ebd09164467beda7b399', 'scripts/prism_match_details.py': '0f7fb79de0a65e60dfcb914716c99562fa44dd7673e6c1c0ea5ee4916ba11bc4', 'scripts/prism_notebook_arena.py': '84baf17c3e9fb31638bb5e56799ceffaec41b96a7a358b289023ab55a6f7b935', 'scripts/prism_notebook_report.py': 'bc7dd35146d795c28c8f8a7fb3910cfe3b832e88884de32b93a0d010ff6fd9ec', 'scripts/prism_ppo_fixed_eval.py': 'fb6683d0f0d91d92efafef1d136545b3dabf376e014e066b19beb43fe78aeacb'} |




## Prism Alpha v0.1.5 对阵 Prism Alpha v0.1.4



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 2625/43/2332 | 52.5000% | 52.9300% | 51.1400% / 53.8200% | 51.5898% / 54.2600% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1387/15/1098 | 55.4800 | 55.7800 | 14.3416 | 13.9276 |
| P1（后手） | 2500 | 1238/28/1234 | 49.5200 | 50.0800 | 14.2408 | 14.0668 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.2912 | 13.9972 |
| VP/本人全部决策 | 0.5158 | 0.5051 |
| VP/本人Main | 0.5159 | 0.5052 |
| VP/全局ply | 0.2579 | 0.2526 |
| 永久折扣/购卡每局 | 11.8318 | 11.8718 |
| 贵族/局 | 0.4532 | 0.4516 |
| 获得贵族的对局% | 38.0200 | 37.6400 |
| 预留获取/局 | 3.2108 | 3.1992 |
| 预留买回/局 | 1.2338 | 1.2598 |
| 终局未买回预留/局 | 1.9770 | 1.9394 |
| 预留买回/获取%（总分母） | 38.4266 | 39.3786 |
| 购入0 VP卡/局 | 5.9776 | 6.1492 |
| 购入1 VP卡/局 | 2.1124 | 2.0142 |
| 购入2 VP卡/局 | 1.8222 | 1.8404 |
| 购入3 VP卡/局 | 0.8326 | 0.8402 |
| 购入4 VP卡/局 | 0.7580 | 0.7122 |
| 购入5 VP卡/局 | 0.3290 | 0.3156 |
| White折扣/局 | 2.4670 | 2.3326 |
| Blue折扣/局 | 2.1870 | 2.3640 |
| Green折扣/局 | 2.3236 | 2.3828 |
| Red折扣/局 | 2.4052 | 2.3728 |
| Black折扣/局 | 2.4490 | 2.4196 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 52990 / 38.2478% | 53060 / 38.2966% |
| buy_reserved | 6169 / 4.4527% | 6299 / 4.5464% |
| take_tokens | 63304 / 45.6923% | 63162 / 45.5879% |
| reserve_market | 16052 / 11.5862% | 15995 / 11.5446% |
| reserve_deck | 2 / 0.0014% | 1 / 0.0007% |
| choose_noble | 26 / 0.0188% | 32 / 0.0231% |
| pass | 1 / 0.0007% | 1 / 0.0007% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 277094 / 55.4188 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 27.7152 / 20.0000 / 27.0000 / 4055.0000 / 56.9915 |
| Main轮均值 | 27.7036 |
| 绝对终局分差 | 3.5112 |
| 分差≤2对局% | 38.3600 |
| 对局监督墙钟秒：累计 / 均 / P95 | 2472.0528 / 0.4944 / 0.6968 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', 'sha256': '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/alpha.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/alpha.json', 'sha256': 'd3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




## Prism Alpha v0.1.5 对阵 Prism Balance v0.1.0



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 2592/40/2368 | 51.8400% | 52.2400% | 50.5600% / 53.1000% | 50.9600% / 53.5000% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1353/17/1130 | 54.1200 | 54.4600 | 14.2352 | 14.0272 |
| P1（后手） | 2500 | 1239/23/1238 | 49.5600 | 50.0200 | 14.1812 | 14.0524 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.2082 | 14.0398 |
| VP/本人全部决策 | 0.5265 | 0.5202 |
| VP/本人Main | 0.5266 | 0.5204 |
| VP/全局ply | 0.2633 | 0.2601 |
| 永久折扣/购卡每局 | 11.7948 | 11.9264 |
| 贵族/局 | 0.4352 | 0.4536 |
| 获得贵族的对局% | 36.1200 | 37.6600 |
| 预留获取/局 | 3.2116 | 3.2796 |
| 预留买回/局 | 1.2546 | 1.2970 |
| 终局未买回预留/局 | 1.9570 | 1.9826 |
| 预留买回/获取%（总分母） | 39.0646 | 39.5475 |
| 购入0 VP卡/局 | 5.9504 | 6.0880 |
| 购入1 VP卡/局 | 2.0866 | 2.1236 |
| 购入2 VP卡/局 | 1.8518 | 1.8744 |
| 购入3 VP卡/局 | 0.8402 | 0.8506 |
| 购入4 VP卡/局 | 0.7372 | 0.6942 |
| 购入5 VP卡/局 | 0.3286 | 0.2956 |
| White折扣/局 | 2.4408 | 2.4004 |
| Blue折扣/局 | 2.2046 | 2.3638 |
| Green折扣/局 | 2.3388 | 2.3596 |
| Red折扣/局 | 2.3980 | 2.3704 |
| Black折扣/局 | 2.4126 | 2.4322 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 52701 / 39.0615% | 53147 / 39.3859% |
| buy_reserved | 6273 / 4.6495% | 6485 / 4.8059% |
| take_tokens | 59864 / 44.3707% | 58866 / 43.6242% |
| reserve_market | 16057 / 11.9013% | 16396 / 12.1507% |
| reserve_deck | 1 / 0.0007% | 2 / 0.0015% |
| choose_noble | 22 / 0.0163% | 43 / 0.0319% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 269857 / 53.9714 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.9920 / 20.0000 / 27.0000 / 256.0000 / 3.7272 |
| Main轮均值 | 26.9792 |
| 绝对终局分差 | 3.5544 |
| 分差≤2对局% | 37.0800 |
| 对局监督墙钟秒：累计 / 均 / P95 | 2386.2043 / 0.4772 / 0.6662 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', 'sha256': '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/balance.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/balance.json', 'sha256': '225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




## Prism Alpha v0.1.5 对阵 Prism Beta v0.1.0



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 2478/53/2469 | 49.5600% | 50.0900% | 48.2600% / 50.8600% | 48.8000% / 51.3800% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1303/24/1173 | 52.1200 | 52.6000 | 14.2380 | 14.0996 |
| P1（后手） | 2500 | 1175/29/1296 | 47.0000 | 47.5800 | 14.0296 | 14.1856 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.1338 | 14.1426 |
| VP/本人全部决策 | 0.5248 | 0.5251 |
| VP/本人Main | 0.5249 | 0.5253 |
| VP/全局ply | 0.2624 | 0.2626 |
| 永久折扣/购卡每局 | 11.8058 | 11.7820 |
| 贵族/局 | 0.4398 | 0.4366 |
| 获得贵族的对局% | 36.3200 | 36.6800 |
| 预留获取/局 | 3.1858 | 3.4740 |
| 预留买回/局 | 1.2432 | 1.3988 |
| 终局未买回预留/局 | 1.9426 | 2.0752 |
| 预留买回/获取%（总分母） | 39.0232 | 40.2648 |
| 购入0 VP卡/局 | 5.9766 | 5.9506 |
| 购入1 VP卡/局 | 2.0852 | 2.0850 |
| 购入2 VP卡/局 | 1.8458 | 1.8690 |
| 购入3 VP卡/局 | 0.8628 | 0.8260 |
| 购入4 VP卡/局 | 0.7278 | 0.7252 |
| 购入5 VP卡/局 | 0.3076 | 0.3262 |
| White折扣/局 | 2.4396 | 2.3716 |
| Blue折扣/局 | 2.2650 | 2.2906 |
| Green折扣/局 | 2.3568 | 2.2946 |
| Red折扣/局 | 2.3528 | 2.4012 |
| Black折扣/局 | 2.3916 | 2.4240 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 52813 / 39.2210% | 51916 / 38.5554% |
| buy_reserved | 6216 / 4.6162% | 6994 / 5.1941% |
| take_tokens | 59666 / 44.3103% | 58345 / 43.3299% |
| reserve_market | 15929 / 11.8295% | 17369 / 12.8991% |
| reserve_deck | 0 / 0.0000% | 1 / 0.0007% |
| choose_noble | 30 / 0.0223% | 28 / 0.0208% |
| pass | 1 / 0.0007% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 269308 / 53.8616 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.9366 / 20.0000 / 27.0000 / 34.0000 / 1.7585 |
| Main轮均值 | 26.9250 |
| 绝对终局分差 | 3.5300 |
| 分差≤2对局% | 37.3000 |
| 对局监督墙钟秒：累计 / 均 / P95 | 2446.6203 / 0.4893 / 0.6806 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', 'sha256': '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/beta.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/beta.json', 'sha256': '69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




## Prism Alpha v0.1.5 对阵 Prism v0.1.1



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 3241/42/1717 | 64.8200% | 65.2400% | 63.4800% / 66.1200% | 63.9200% / 66.5300% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1677/16/807 | 67.0800 | 67.4000 | 14.8460 | 13.2360 |
| P1（后手） | 2500 | 1564/26/910 | 62.5600 | 63.0800 | 14.7652 | 13.3432 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.8056 | 13.2896 |
| VP/本人全部决策 | 0.5450 | 0.4892 |
| VP/本人Main | 0.5451 | 0.4893 |
| VP/全局ply | 0.2725 | 0.2446 |
| 永久折扣/购卡每局 | 11.7546 | 12.3982 |
| 贵族/局 | 0.4482 | 0.5014 |
| 获得贵族的对局% | 38.0400 | 39.8600 |
| 预留获取/局 | 2.9934 | 2.6220 |
| 预留买回/局 | 1.1732 | 1.0866 |
| 终局未买回预留/局 | 1.8202 | 1.5354 |
| 预留买回/获取%（总分母） | 39.1929 | 41.4416 |
| 购入0 VP卡/局 | 5.8418 | 6.6264 |
| 购入1 VP卡/局 | 1.9936 | 2.3316 |
| 购入2 VP卡/局 | 1.8700 | 1.8410 |
| 购入3 VP卡/局 | 0.8526 | 0.8292 |
| 购入4 VP卡/局 | 0.8134 | 0.5658 |
| 购入5 VP卡/局 | 0.3832 | 0.2042 |
| White折扣/局 | 2.4650 | 2.4222 |
| Blue折扣/局 | 2.1192 | 2.6318 |
| Green折扣/局 | 2.3110 | 2.4646 |
| Red折扣/局 | 2.3848 | 2.4750 |
| Black折扣/局 | 2.4746 | 2.4046 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 52907 / 38.9523% | 56558 / 41.6348% |
| buy_reserved | 5866 / 4.3188% | 5433 / 3.9995% |
| take_tokens | 62055 / 45.6875% | 60694 / 44.6795% |
| reserve_market | 14966 / 11.0186% | 13110 / 9.6508% |
| reserve_deck | 1 / 0.0007% | 0 / 0.0000% |
| choose_noble | 30 / 0.0221% | 48 / 0.0353% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 271668 / 54.3336 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 27.1736 / 20.0000 / 27.0000 / 1423.0000 / 23.7740 |
| Main轮均值 | 27.1590 |
| 绝对终局分差 | 3.7504 |
| 分差≤2对局% | 34.3200 |
| 对局监督墙钟秒：累计 / 均 / P95 | 2359.0581 / 0.4718 / 0.6466 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', 'sha256': '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/general.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/general.json', 'sha256': 'a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




## Prism Alpha v0.1.5 对阵 Heuristic v0.3.1



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 4019/22/959 | 80.3800% | 80.6000% | 79.2800% / 81.5000% | 79.5000% / 81.7000% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 2047/13/440 | 81.8800 | 82.1400 | 15.4872 | 12.0764 |
| P1（后手） | 2500 | 1972/9/519 | 78.8800 | 79.0600 | 15.4188 | 12.1892 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 15.4530 | 12.1328 |
| VP/本人全部决策 | 0.5869 | 0.4606 |
| VP/本人Main | 0.5870 | 0.4609 |
| VP/全局ply | 0.2934 | 0.2303 |
| 永久折扣/购卡每局 | 11.7146 | 12.8518 |
| 贵族/局 | 0.4104 | 0.5716 |
| 获得贵族的对局% | 34.8400 | 42.7600 |
| 预留获取/局 | 2.5902 | 2.4548 |
| 预留买回/局 | 0.9720 | 1.2546 |
| 终局未买回预留/局 | 1.6182 | 1.2002 |
| 预留买回/获取%（总分母） | 37.5261 | 51.1080 |
| 购入0 VP卡/局 | 5.6816 | 7.2900 |
| 购入1 VP卡/局 | 1.9038 | 2.5900 |
| 购入2 VP卡/局 | 1.9124 | 1.7244 |
| 购入3 VP卡/局 | 0.8502 | 0.7290 |
| 购入4 VP卡/局 | 0.8904 | 0.3998 |
| 购入5 VP卡/局 | 0.4762 | 0.1186 |
| White折扣/局 | 2.4100 | 2.5480 |
| Blue折扣/局 | 2.2092 | 2.6300 |
| Green折扣/局 | 2.2870 | 2.5770 |
| Red折扣/局 | 2.3756 | 2.5840 |
| Black折扣/局 | 2.4328 | 2.5128 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 53713 / 40.7992% | 57986 / 44.0235% |
| buy_reserved | 4860 / 3.6916% | 6273 / 4.7625% |
| take_tokens | 60106 / 45.6552% | 55097 / 41.8301% |
| reserve_market | 12951 / 9.8373% | 12190 / 9.2548% |
| reserve_deck | 0 / 0.0000% | 84 / 0.0638% |
| choose_noble | 22 / 0.0167% | 86 / 0.0653% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 263368 / 52.6736 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.3468 / 20.0000 / 26.0000 / 32.0000 / 1.7853 |
| Main轮均值 | 26.3260 |
| 绝对终局分差 | 4.4370 |
| 分差≤2对局% | 27.3200 |
| 对局监督墙钟秒：累计 / 均 / P95 | 1469.3851 / 0.2939 / 0.4304 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', 'sha256': '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-heuristic-v02', '--seed', '67020001'], 'files': [], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




## Prism Alpha v0.1.5 对阵 Prism v0.1.0



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 3969/22/1009 | 79.3800% | 79.6000% | 78.2400% / 80.5000% | 78.4800% / 80.7200% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 2018/10/472 | 80.7200 | 80.9200 | 15.3352 | 12.0388 |
| P1（后手） | 2500 | 1951/12/537 | 78.0400 | 78.2800 | 15.2632 | 12.2052 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 15.2992 | 12.1220 |
| VP/本人全部决策 | 0.5807 | 0.4599 |
| VP/本人Main | 0.5808 | 0.4602 |
| VP/全局ply | 0.2903 | 0.2300 |
| 永久折扣/购卡每局 | 11.7376 | 13.0182 |
| 贵族/局 | 0.4304 | 0.5580 |
| 获得贵族的对局% | 36.5200 | 42.1000 |
| 预留获取/局 | 2.6664 | 1.9544 |
| 预留买回/局 | 1.0204 | 0.9722 |
| 终局未买回预留/局 | 1.6460 | 0.9822 |
| 预留买回/获取%（总分母） | 38.2688 | 49.7442 |
| 购入0 VP卡/局 | 5.7294 | 7.4262 |
| 购入1 VP卡/局 | 1.9274 | 2.6034 |
| 购入2 VP卡/局 | 1.9146 | 1.7526 |
| 购入3 VP卡/局 | 0.8570 | 0.7216 |
| 购入4 VP卡/局 | 0.8656 | 0.3974 |
| 购入5 VP卡/局 | 0.4436 | 0.1170 |
| White折扣/局 | 2.4216 | 2.5570 |
| Blue折扣/局 | 2.1468 | 2.7580 |
| Green折扣/局 | 2.3220 | 2.5876 |
| Red折扣/局 | 2.4296 | 2.5106 |
| Black折扣/局 | 2.4176 | 2.6050 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 53586 / 40.6784% | 60230 / 45.6991% |
| buy_reserved | 5102 / 3.8730% | 4861 / 3.6882% |
| take_tokens | 59692 / 45.3136% | 56849 / 43.1338% |
| reserve_market | 13332 / 10.1206% | 9756 / 7.4023% |
| reserve_deck | 0 / 0.0000% | 16 / 0.0121% |
| choose_noble | 19 / 0.0144% | 85 / 0.0645% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 263528 / 52.7056 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.3628 / 19.0000 / 26.0000 / 34.0000 / 1.8558 |
| Main轮均值 | 26.3424 |
| 绝对终局分差 | 4.4036 |
| 分差≤2对局% | 26.8800 |
| 对局监督墙钟秒：累计 / 均 / P95 | 2255.6907 / 0.4511 / 0.6246 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', 'sha256': '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/initial.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/initial.json', 'sha256': '5db70b773083858b83c6e679d5641f1b78d4c5fbe34c48950cc906064f821b54'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |



# a-common 原始完整报告

# Prism 通用对战结果（DSW / SSH - 已恢复带缺项）



**产物：已完成 29995 局，Rust规则回放验核与双方指标守恒通过。有 1 个保留缺项（步数安全限制死锁或孤立中断），未自动重试，未捏造平局。**



**竞技：DEVELOPMENT_ONLY_NOT_PROMOTED。**这是独立通用开发测量，保留缺项未执行完整晋级。



**风格：描述性数据。**不凭单一更高/更低经济指标授予风格身份。



候选按用户声明的完整模型名及导出SHA识别。



## 候选匹配比较





## M67种子A最终c20未发布训练检查点 对阵 Prism Alpha v0.1.4



被测模型模式：greedy；对手模式：greedy。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 3072/45/1883 | 61.4400% | 61.8900% | 60.1000% / 62.7600% | 60.5600% / 63.2000% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1614/28/858 | 64.5600 | 65.1200 | 14.6672 | 13.3540 |
| P1（后手） | 2500 | 1458/17/1025 | 58.3200 | 58.6600 | 14.5224 | 13.4684 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.5948 | 13.4112 |
| VP/本人全部决策 | 0.5438 | 0.4996 |
| VP/本人Main | 0.5439 | 0.4998 |
| 永久折扣/购卡每局 | 11.2134 | 11.7838 |
| 贵族/局 | 0.3628 | 0.4384 |
| 获得贵族的对局% | 31.2200 | 36.1400 |
| 预留获取/局 | 3.6116 | 3.2500 |
| 预留买回/局 | 1.5422 | 1.3088 |




## M67种子A最终c20未发布训练检查点 对阵 Prism Balance v0.1.0



被测模型模式：greedy；对手模式：greedy。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 4999/2499 | 3052/42/1905 | 61.0522% | 61.4723% | 59.7439% / 62.3249% | 60.1741% / 62.7451% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1565/26/909 | 62.6000 | 63.1200 | 14.6804 | 13.5128 |
| P1（后手） | 2499 | 1487/16/996 | 59.5038 | 59.8239 | 14.6214 | 13.5314 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.6509 | 13.5221 |
| VP/本人全部决策 | 0.5343 | 0.4930 |
| VP/本人Main | 0.5343 | 0.4932 |
| 永久折扣/购卡每局 | 11.2737 | 11.8936 |
| 贵族/局 | 0.3677 | 0.4585 |
| 获得贵族的对局% | 31.6063 | 37.7075 |
| 预留获取/局 | 3.6479 | 3.3039 |
| 预留买回/局 | 1.5735 | 1.3081 |




## M67种子A最终c20未发布训练检查点 对阵 Prism Beta v0.1.0



被测模型模式：greedy；对手模式：greedy。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 2972/39/1989 | 59.4400% | 59.8300% | 58.1400% / 60.7400% | 58.5400% / 61.1200% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1522/22/956 | 60.8800 | 61.3200 | 14.5716 | 13.5772 |
| P1（后手） | 2500 | 1450/17/1033 | 58.0000 | 58.3400 | 14.5064 | 13.4840 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.5390 | 13.5306 |
| VP/本人全部决策 | 0.5413 | 0.5037 |
| VP/本人Main | 0.5414 | 0.5038 |
| 永久折扣/购卡每局 | 11.2668 | 11.7724 |
| 贵族/局 | 0.3674 | 0.4292 |
| 获得贵族的对局% | 32.3400 | 35.9400 |
| 预留获取/局 | 3.5858 | 3.5138 |
| 预留买回/局 | 1.5382 | 1.4168 |




## M67种子A最终c20未发布训练检查点 对阵 Prism v0.1.1



被测模型模式：greedy；对手模式：greedy。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 4996/2496 | 3644/32/1320 | 72.9384% | 73.2586% | 71.7147% / 74.1386% | 72.0450% / 74.4491% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2498 | 1866/15/617 | 74.6998 | 75.0000 | 15.1069 | 12.6469 |
| P1（后手） | 2498 | 1778/17/703 | 71.1769 | 71.5172 | 15.0532 | 12.7894 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 15.0801 | 12.7182 |
| VP/本人全部决策 | 0.5446 | 0.4592 |
| VP/本人Main | 0.5447 | 0.4594 |
| 永久折扣/购卡每局 | 11.2186 | 12.2762 |
| 贵族/局 | 0.3599 | 0.4734 |
| 获得贵族的对局% | 31.4652 | 38.3307 |
| 预留获取/局 | 3.4125 | 2.6884 |
| 预留买回/局 | 1.4698 | 1.1435 |




## M67种子A最终c20未发布训练检查点 对阵 Heuristic v0.3.1



被测模型模式：greedy；对手模式：greedy。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 4215/16/769 | 84.3000% | 84.4600% | 83.3000% / 85.3000% | 83.4600% / 85.4500% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 2132/8/360 | 85.2800 | 85.4400 | 15.5580 | 11.5616 |
| P1（后手） | 2500 | 2083/8/409 | 83.3200 | 83.4800 | 15.4876 | 11.6064 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 15.5228 | 11.5840 |
| VP/本人全部决策 | 0.5929 | 0.4422 |
| VP/本人Main | 0.5930 | 0.4425 |
| 永久折扣/购卡每局 | 11.1326 | 12.6914 |
| 贵族/局 | 0.3312 | 0.5666 |
| 获得贵族的对局% | 29.0000 | 41.6000 |
| 预留获取/局 | 3.0068 | 2.5462 |
| 预留买回/局 | 1.2408 | 1.3118 |




## M67种子A最终c20未发布训练检查点 对阵 Prism v0.1.0



被测模型模式：greedy；对手模式：greedy。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 4267/9/724 | 85.3400% | 85.4300% | 84.3600% / 86.3200% | 84.4600% / 86.4100% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 2151/6/343 | 86.0400 | 86.1600 | 15.5048 | 11.3840 |
| P1（后手） | 2500 | 2116/3/381 | 84.6400 | 84.7000 | 15.4768 | 11.5212 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 15.4908 | 11.4526 |
| VP/本人全部决策 | 0.5914 | 0.4370 |
| VP/本人Main | 0.5915 | 0.4373 |
| 永久折扣/购卡每局 | 11.1432 | 12.7446 |
| 贵族/局 | 0.3476 | 0.5054 |
| 获得贵族的对局% | 30.5800 | 38.2400 |
| 预留获取/局 | 3.1070 | 2.0524 |
| 预留买回/局 | 1.3164 | 1.0486 |



# b-common 原始完整报告

# Prism 通用对战结果（DSW / SSH）



**产物：已完成全部固定网格，Rust规则回放验核与双方指标守恒通过。**



**竞技：DEVELOPMENT_ONLY_NOT_PROMOTED。**这是独立通用开发测量，没有执行任何里程碑正式晋级门。



**风格：描述性数据。**不凭单一更高/更低经济指标授予风格身份。



候选按用户声明的完整模型名及导出SHA识别，未发布检查点仍须在名称中明确标注。每对手恰好双座种子块；个人表按模型身份归并，物理P0不总是候选。



## 候选匹配比较



只有一个候选，匹配基线到候选比较NOT_APPLICABLE。

↑/↓仅为方向标记，不表示更好或差异显著。下面CI为逐对手描述性双座bootstrap；不做多门验收或发布。若只有一个种子块，CI退化，不能据此确认稳定性。



## 总体执行与来源



| 字段 | 记录 |
| --- | --- |
| 固定局数 | 30000 |
| 并发进程 / 每进程库线程 | 4 / 1 |
| 累计已测活动墙钟秒（至报告前监测点） | 6711.2317 |
| 首次派发至报告生成秒（包含暂停） | 6823.8491 |
| 时钟范围 | standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download |
| 资源监控 | observed process-tree soft limits; shared platform cgroups are not owned |
| 已测负载 | {'observed_processes': 2, 'peak_observed_rss_bytes': 247513088, 'process_tree_cpu_seconds': 19007.71, 'process_tree_rss_sum_bytes': 31887360, 'scope': 'sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages', 'storage_bytes': 915710596} |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |
| 配置SHA256 | c89d92f50b0c460ce3e92847b8fcc81dae3603b507c0079e11a425a089735775 |
| plan SHA256 | 4fdda24703777b009954b11a7e078c40358a7ea36c7b48c7a9b2697d5fa97668 |
| engine SHA256 | 6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f |
| metrics SHA256 | 39c630d5e0a9e0611ca4ec8c8b2e4a78817bf971c7bdc7446b614035aedbcb37 |
| Git基线 / 源码dirty | NOT_AVAILABLE / None |
| Bootstrap | {'kind': 'descriptive paired seed blocks, not acceptance', 'samples': 20000, 'seed': 64049999} |
| 种子 | [9830000, 9830001, 9830002, 9830003, 9830004, 9830005, 9830006, 9830007, 9830008, 9830009, 9830010, 9830011, 9830012, 9830013, 9830014, 9830015, 9830016, 9830017, 9830018, 9830019, 9830020, 9830021, 9830022, 9830023, 9830024, 9830025, 9830026, 9830027, 9830028, 9830029, 9830030, 9830031, 9830032, 9830033, 9830034, 9830035, 9830036, 9830037, 9830038, 9830039, 9830040, 9830041, 9830042, 9830043, 9830044, 9830045, 9830046, 9830047, 9830048, 9830049, 9830050, 9830051, 9830052, 9830053, 9830054, 9830055, 9830056, 9830057, 9830058, 9830059, 9830060, 9830061, 9830062, 9830063, 9830064, 9830065, 9830066, 9830067, 9830068, 9830069, 9830070, 9830071, 9830072, 9830073, 9830074, 9830075, 9830076, 9830077, 9830078, 9830079, 9830080, 9830081, 9830082, 9830083, 9830084, 9830085, 9830086, 9830087, 9830088, 9830089, 9830090, 9830091, 9830092, 9830093, 9830094, 9830095, 9830096, 9830097, 9830098, 9830099, 9830100, 9830101, 9830102, 9830103, 9830104, 9830105, 9830106, 9830107, 9830108, 9830109, 9830110, 9830111, 9830112, 9830113, 9830114, 9830115, 9830116, 9830117, 9830118, 9830119, 9830120, 9830121, 9830122, 9830123, 9830124, 9830125, 9830126, 9830127, 9830128, 9830129, 9830130, 9830131, 9830132, 9830133, 9830134, 9830135, 9830136, 9830137, 9830138, 9830139, 9830140, 9830141, 9830142, 9830143, 9830144, 9830145, 9830146, 9830147, 9830148, 9830149, 9830150, 9830151, 9830152, 9830153, 9830154, 9830155, 9830156, 9830157, 9830158, 9830159, 9830160, 9830161, 9830162, 9830163, 9830164, 9830165, 9830166, 9830167, 9830168, 9830169, 9830170, 9830171, 9830172, 9830173, 9830174, 9830175, 9830176, 9830177, 9830178, 9830179, 9830180, 9830181, 9830182, 9830183, 9830184, 9830185, 9830186, 9830187, 9830188, 9830189, 9830190, 9830191, 9830192, 9830193, 9830194, 9830195, 9830196, 9830197, 9830198, 9830199, 9830200, 9830201, 9830202, 9830203, 9830204, 9830205, 9830206, 9830207, 9830208, 9830209, 9830210, 9830211, 9830212, 9830213, 9830214, 9830215, 9830216, 9830217, 9830218, 9830219, 9830220, 9830221, 9830222, 9830223, 9830224, 9830225, 9830226, 9830227, 9830228, 9830229, 9830230, 9830231, 9830232, 9830233, 9830234, 9830235, 9830236, 9830237, 9830238, 9830239, 9830240, 9830241, 9830242, 9830243, 9830244, 9830245, 9830246, 9830247, 9830248, 9830249, 9830250, 9830251, 9830252, 9830253, 9830254, 9830255, 9830256, 9830257, 9830258, 9830259, 9830260, 9830261, 9830262, 9830263, 9830264, 9830265, 9830266, 9830267, 9830268, 9830269, 9830270, 9830271, 9830272, 9830273, 9830274, 9830275, 9830276, 9830277, 9830278, 9830279, 9830280, 9830281, 9830282, 9830283, 9830284, 9830285, 9830286, 9830287, 9830288, 9830289, 9830290, 9830291, 9830292, 9830293, 9830294, 9830295, 9830296, 9830297, 9830298, 9830299, 9830300, 9830301, 9830302, 9830303, 9830304, 9830305, 9830306, 9830307, 9830308, 9830309, 9830310, 9830311, 9830312, 9830313, 9830314, 9830315, 9830316, 9830317, 9830318, 9830319, 9830320, 9830321, 9830322, 9830323, 9830324, 9830325, 9830326, 9830327, 9830328, 9830329, 9830330, 9830331, 9830332, 9830333, 9830334, 9830335, 9830336, 9830337, 9830338, 9830339, 9830340, 9830341, 9830342, 9830343, 9830344, 9830345, 9830346, 9830347, 9830348, 9830349, 9830350, 9830351, 9830352, 9830353, 9830354, 9830355, 9830356, 9830357, 9830358, 9830359, 9830360, 9830361, 9830362, 9830363, 9830364, 9830365, 9830366, 9830367, 9830368, 9830369, 9830370, 9830371, 9830372, 9830373, 9830374, 9830375, 9830376, 9830377, 9830378, 9830379, 9830380, 9830381, 9830382, 9830383, 9830384, 9830385, 9830386, 9830387, 9830388, 9830389, 9830390, 9830391, 9830392, 9830393, 9830394, 9830395, 9830396, 9830397, 9830398, 9830399, 9830400, 9830401, 9830402, 9830403, 9830404, 9830405, 9830406, 9830407, 9830408, 9830409, 9830410, 9830411, 9830412, 9830413, 9830414, 9830415, 9830416, 9830417, 9830418, 9830419, 9830420, 9830421, 9830422, 9830423, 9830424, 9830425, 9830426, 9830427, 9830428, 9830429, 9830430, 9830431, 9830432, 9830433, 9830434, 9830435, 9830436, 9830437, 9830438, 9830439, 9830440, 9830441, 9830442, 9830443, 9830444, 9830445, 9830446, 9830447, 9830448, 9830449, 9830450, 9830451, 9830452, 9830453, 9830454, 9830455, 9830456, 9830457, 9830458, 9830459, 9830460, 9830461, 9830462, 9830463, 9830464, 9830465, 9830466, 9830467, 9830468, 9830469, 9830470, 9830471, 9830472, 9830473, 9830474, 9830475, 9830476, 9830477, 9830478, 9830479, 9830480, 9830481, 9830482, 9830483, 9830484, 9830485, 9830486, 9830487, 9830488, 9830489, 9830490, 9830491, 9830492, 9830493, 9830494, 9830495, 9830496, 9830497, 9830498, 9830499, 9830500, 9830501, 9830502, 9830503, 9830504, 9830505, 9830506, 9830507, 9830508, 9830509, 9830510, 9830511, 9830512, 9830513, 9830514, 9830515, 9830516, 9830517, 9830518, 9830519, 9830520, 9830521, 9830522, 9830523, 9830524, 9830525, 9830526, 9830527, 9830528, 9830529, 9830530, 9830531, 9830532, 9830533, 9830534, 9830535, 9830536, 9830537, 9830538, 9830539, 9830540, 9830541, 9830542, 9830543, 9830544, 9830545, 9830546, 9830547, 9830548, 9830549, 9830550, 9830551, 9830552, 9830553, 9830554, 9830555, 9830556, 9830557, 9830558, 9830559, 9830560, 9830561, 9830562, 9830563, 9830564, 9830565, 9830566, 9830567, 9830568, 9830569, 9830570, 9830571, 9830572, 9830573, 9830574, 9830575, 9830576, 9830577, 9830578, 9830579, 9830580, 9830581, 9830582, 9830583, 9830584, 9830585, 9830586, 9830587, 9830588, 9830589, 9830590, 9830591, 9830592, 9830593, 9830594, 9830595, 9830596, 9830597, 9830598, 9830599, 9830600, 9830601, 9830602, 9830603, 9830604, 9830605, 9830606, 9830607, 9830608, 9830609, 9830610, 9830611, 9830612, 9830613, 9830614, 9830615, 9830616, 9830617, 9830618, 9830619, 9830620, 9830621, 9830622, 9830623, 9830624, 9830625, 9830626, 9830627, 9830628, 9830629, 9830630, 9830631, 9830632, 9830633, 9830634, 9830635, 9830636, 9830637, 9830638, 9830639, 9830640, 9830641, 9830642, 9830643, 9830644, 9830645, 9830646, 9830647, 9830648, 9830649, 9830650, 9830651, 9830652, 9830653, 9830654, 9830655, 9830656, 9830657, 9830658, 9830659, 9830660, 9830661, 9830662, 9830663, 9830664, 9830665, 9830666, 9830667, 9830668, 9830669, 9830670, 9830671, 9830672, 9830673, 9830674, 9830675, 9830676, 9830677, 9830678, 9830679, 9830680, 9830681, 9830682, 9830683, 9830684, 9830685, 9830686, 9830687, 9830688, 9830689, 9830690, 9830691, 9830692, 9830693, 9830694, 9830695, 9830696, 9830697, 9830698, 9830699, 9830700, 9830701, 9830702, 9830703, 9830704, 9830705, 9830706, 9830707, 9830708, 9830709, 9830710, 9830711, 9830712, 9830713, 9830714, 9830715, 9830716, 9830717, 9830718, 9830719, 9830720, 9830721, 9830722, 9830723, 9830724, 9830725, 9830726, 9830727, 9830728, 9830729, 9830730, 9830731, 9830732, 9830733, 9830734, 9830735, 9830736, 9830737, 9830738, 9830739, 9830740, 9830741, 9830742, 9830743, 9830744, 9830745, 9830746, 9830747, 9830748, 9830749, 9830750, 9830751, 9830752, 9830753, 9830754, 9830755, 9830756, 9830757, 9830758, 9830759, 9830760, 9830761, 9830762, 9830763, 9830764, 9830765, 9830766, 9830767, 9830768, 9830769, 9830770, 9830771, 9830772, 9830773, 9830774, 9830775, 9830776, 9830777, 9830778, 9830779, 9830780, 9830781, 9830782, 9830783, 9830784, 9830785, 9830786, 9830787, 9830788, 9830789, 9830790, 9830791, 9830792, 9830793, 9830794, 9830795, 9830796, 9830797, 9830798, 9830799, 9830800, 9830801, 9830802, 9830803, 9830804, 9830805, 9830806, 9830807, 9830808, 9830809, 9830810, 9830811, 9830812, 9830813, 9830814, 9830815, 9830816, 9830817, 9830818, 9830819, 9830820, 9830821, 9830822, 9830823, 9830824, 9830825, 9830826, 9830827, 9830828, 9830829, 9830830, 9830831, 9830832, 9830833, 9830834, 9830835, 9830836, 9830837, 9830838, 9830839, 9830840, 9830841, 9830842, 9830843, 9830844, 9830845, 9830846, 9830847, 9830848, 9830849, 9830850, 9830851, 9830852, 9830853, 9830854, 9830855, 9830856, 9830857, 9830858, 9830859, 9830860, 9830861, 9830862, 9830863, 9830864, 9830865, 9830866, 9830867, 9830868, 9830869, 9830870, 9830871, 9830872, 9830873, 9830874, 9830875, 9830876, 9830877, 9830878, 9830879, 9830880, 9830881, 9830882, 9830883, 9830884, 9830885, 9830886, 9830887, 9830888, 9830889, 9830890, 9830891, 9830892, 9830893, 9830894, 9830895, 9830896, 9830897, 9830898, 9830899, 9830900, 9830901, 9830902, 9830903, 9830904, 9830905, 9830906, 9830907, 9830908, 9830909, 9830910, 9830911, 9830912, 9830913, 9830914, 9830915, 9830916, 9830917, 9830918, 9830919, 9830920, 9830921, 9830922, 9830923, 9830924, 9830925, 9830926, 9830927, 9830928, 9830929, 9830930, 9830931, 9830932, 9830933, 9830934, 9830935, 9830936, 9830937, 9830938, 9830939, 9830940, 9830941, 9830942, 9830943, 9830944, 9830945, 9830946, 9830947, 9830948, 9830949, 9830950, 9830951, 9830952, 9830953, 9830954, 9830955, 9830956, 9830957, 9830958, 9830959, 9830960, 9830961, 9830962, 9830963, 9830964, 9830965, 9830966, 9830967, 9830968, 9830969, 9830970, 9830971, 9830972, 9830973, 9830974, 9830975, 9830976, 9830977, 9830978, 9830979, 9830980, 9830981, 9830982, 9830983, 9830984, 9830985, 9830986, 9830987, 9830988, 9830989, 9830990, 9830991, 9830992, 9830993, 9830994, 9830995, 9830996, 9830997, 9830998, 9830999, 9831000, 9831001, 9831002, 9831003, 9831004, 9831005, 9831006, 9831007, 9831008, 9831009, 9831010, 9831011, 9831012, 9831013, 9831014, 9831015, 9831016, 9831017, 9831018, 9831019, 9831020, 9831021, 9831022, 9831023, 9831024, 9831025, 9831026, 9831027, 9831028, 9831029, 9831030, 9831031, 9831032, 9831033, 9831034, 9831035, 9831036, 9831037, 9831038, 9831039, 9831040, 9831041, 9831042, 9831043, 9831044, 9831045, 9831046, 9831047, 9831048, 9831049, 9831050, 9831051, 9831052, 9831053, 9831054, 9831055, 9831056, 9831057, 9831058, 9831059, 9831060, 9831061, 9831062, 9831063, 9831064, 9831065, 9831066, 9831067, 9831068, 9831069, 9831070, 9831071, 9831072, 9831073, 9831074, 9831075, 9831076, 9831077, 9831078, 9831079, 9831080, 9831081, 9831082, 9831083, 9831084, 9831085, 9831086, 9831087, 9831088, 9831089, 9831090, 9831091, 9831092, 9831093, 9831094, 9831095, 9831096, 9831097, 9831098, 9831099, 9831100, 9831101, 9831102, 9831103, 9831104, 9831105, 9831106, 9831107, 9831108, 9831109, 9831110, 9831111, 9831112, 9831113, 9831114, 9831115, 9831116, 9831117, 9831118, 9831119, 9831120, 9831121, 9831122, 9831123, 9831124, 9831125, 9831126, 9831127, 9831128, 9831129, 9831130, 9831131, 9831132, 9831133, 9831134, 9831135, 9831136, 9831137, 9831138, 9831139, 9831140, 9831141, 9831142, 9831143, 9831144, 9831145, 9831146, 9831147, 9831148, 9831149, 9831150, 9831151, 9831152, 9831153, 9831154, 9831155, 9831156, 9831157, 9831158, 9831159, 9831160, 9831161, 9831162, 9831163, 9831164, 9831165, 9831166, 9831167, 9831168, 9831169, 9831170, 9831171, 9831172, 9831173, 9831174, 9831175, 9831176, 9831177, 9831178, 9831179, 9831180, 9831181, 9831182, 9831183, 9831184, 9831185, 9831186, 9831187, 9831188, 9831189, 9831190, 9831191, 9831192, 9831193, 9831194, 9831195, 9831196, 9831197, 9831198, 9831199, 9831200, 9831201, 9831202, 9831203, 9831204, 9831205, 9831206, 9831207, 9831208, 9831209, 9831210, 9831211, 9831212, 9831213, 9831214, 9831215, 9831216, 9831217, 9831218, 9831219, 9831220, 9831221, 9831222, 9831223, 9831224, 9831225, 9831226, 9831227, 9831228, 9831229, 9831230, 9831231, 9831232, 9831233, 9831234, 9831235, 9831236, 9831237, 9831238, 9831239, 9831240, 9831241, 9831242, 9831243, 9831244, 9831245, 9831246, 9831247, 9831248, 9831249, 9831250, 9831251, 9831252, 9831253, 9831254, 9831255, 9831256, 9831257, 9831258, 9831259, 9831260, 9831261, 9831262, 9831263, 9831264, 9831265, 9831266, 9831267, 9831268, 9831269, 9831270, 9831271, 9831272, 9831273, 9831274, 9831275, 9831276, 9831277, 9831278, 9831279, 9831280, 9831281, 9831282, 9831283, 9831284, 9831285, 9831286, 9831287, 9831288, 9831289, 9831290, 9831291, 9831292, 9831293, 9831294, 9831295, 9831296, 9831297, 9831298, 9831299, 9831300, 9831301, 9831302, 9831303, 9831304, 9831305, 9831306, 9831307, 9831308, 9831309, 9831310, 9831311, 9831312, 9831313, 9831314, 9831315, 9831316, 9831317, 9831318, 9831319, 9831320, 9831321, 9831322, 9831323, 9831324, 9831325, 9831326, 9831327, 9831328, 9831329, 9831330, 9831331, 9831332, 9831333, 9831334, 9831335, 9831336, 9831337, 9831338, 9831339, 9831340, 9831341, 9831342, 9831343, 9831344, 9831345, 9831346, 9831347, 9831348, 9831349, 9831350, 9831351, 9831352, 9831353, 9831354, 9831355, 9831356, 9831357, 9831358, 9831359, 9831360, 9831361, 9831362, 9831363, 9831364, 9831365, 9831366, 9831367, 9831368, 9831369, 9831370, 9831371, 9831372, 9831373, 9831374, 9831375, 9831376, 9831377, 9831378, 9831379, 9831380, 9831381, 9831382, 9831383, 9831384, 9831385, 9831386, 9831387, 9831388, 9831389, 9831390, 9831391, 9831392, 9831393, 9831394, 9831395, 9831396, 9831397, 9831398, 9831399, 9831400, 9831401, 9831402, 9831403, 9831404, 9831405, 9831406, 9831407, 9831408, 9831409, 9831410, 9831411, 9831412, 9831413, 9831414, 9831415, 9831416, 9831417, 9831418, 9831419, 9831420, 9831421, 9831422, 9831423, 9831424, 9831425, 9831426, 9831427, 9831428, 9831429, 9831430, 9831431, 9831432, 9831433, 9831434, 9831435, 9831436, 9831437, 9831438, 9831439, 9831440, 9831441, 9831442, 9831443, 9831444, 9831445, 9831446, 9831447, 9831448, 9831449, 9831450, 9831451, 9831452, 9831453, 9831454, 9831455, 9831456, 9831457, 9831458, 9831459, 9831460, 9831461, 9831462, 9831463, 9831464, 9831465, 9831466, 9831467, 9831468, 9831469, 9831470, 9831471, 9831472, 9831473, 9831474, 9831475, 9831476, 9831477, 9831478, 9831479, 9831480, 9831481, 9831482, 9831483, 9831484, 9831485, 9831486, 9831487, 9831488, 9831489, 9831490, 9831491, 9831492, 9831493, 9831494, 9831495, 9831496, 9831497, 9831498, 9831499, 9831500, 9831501, 9831502, 9831503, 9831504, 9831505, 9831506, 9831507, 9831508, 9831509, 9831510, 9831511, 9831512, 9831513, 9831514, 9831515, 9831516, 9831517, 9831518, 9831519, 9831520, 9831521, 9831522, 9831523, 9831524, 9831525, 9831526, 9831527, 9831528, 9831529, 9831530, 9831531, 9831532, 9831533, 9831534, 9831535, 9831536, 9831537, 9831538, 9831539, 9831540, 9831541, 9831542, 9831543, 9831544, 9831545, 9831546, 9831547, 9831548, 9831549, 9831550, 9831551, 9831552, 9831553, 9831554, 9831555, 9831556, 9831557, 9831558, 9831559, 9831560, 9831561, 9831562, 9831563, 9831564, 9831565, 9831566, 9831567, 9831568, 9831569, 9831570, 9831571, 9831572, 9831573, 9831574, 9831575, 9831576, 9831577, 9831578, 9831579, 9831580, 9831581, 9831582, 9831583, 9831584, 9831585, 9831586, 9831587, 9831588, 9831589, 9831590, 9831591, 9831592, 9831593, 9831594, 9831595, 9831596, 9831597, 9831598, 9831599, 9831600, 9831601, 9831602, 9831603, 9831604, 9831605, 9831606, 9831607, 9831608, 9831609, 9831610, 9831611, 9831612, 9831613, 9831614, 9831615, 9831616, 9831617, 9831618, 9831619, 9831620, 9831621, 9831622, 9831623, 9831624, 9831625, 9831626, 9831627, 9831628, 9831629, 9831630, 9831631, 9831632, 9831633, 9831634, 9831635, 9831636, 9831637, 9831638, 9831639, 9831640, 9831641, 9831642, 9831643, 9831644, 9831645, 9831646, 9831647, 9831648, 9831649, 9831650, 9831651, 9831652, 9831653, 9831654, 9831655, 9831656, 9831657, 9831658, 9831659, 9831660, 9831661, 9831662, 9831663, 9831664, 9831665, 9831666, 9831667, 9831668, 9831669, 9831670, 9831671, 9831672, 9831673, 9831674, 9831675, 9831676, 9831677, 9831678, 9831679, 9831680, 9831681, 9831682, 9831683, 9831684, 9831685, 9831686, 9831687, 9831688, 9831689, 9831690, 9831691, 9831692, 9831693, 9831694, 9831695, 9831696, 9831697, 9831698, 9831699, 9831700, 9831701, 9831702, 9831703, 9831704, 9831705, 9831706, 9831707, 9831708, 9831709, 9831710, 9831711, 9831712, 9831713, 9831714, 9831715, 9831716, 9831717, 9831718, 9831719, 9831720, 9831721, 9831722, 9831723, 9831724, 9831725, 9831726, 9831727, 9831728, 9831729, 9831730, 9831731, 9831732, 9831733, 9831734, 9831735, 9831736, 9831737, 9831738, 9831739, 9831740, 9831741, 9831742, 9831743, 9831744, 9831745, 9831746, 9831747, 9831748, 9831749, 9831750, 9831751, 9831752, 9831753, 9831754, 9831755, 9831756, 9831757, 9831758, 9831759, 9831760, 9831761, 9831762, 9831763, 9831764, 9831765, 9831766, 9831767, 9831768, 9831769, 9831770, 9831771, 9831772, 9831773, 9831774, 9831775, 9831776, 9831777, 9831778, 9831779, 9831780, 9831781, 9831782, 9831783, 9831784, 9831785, 9831786, 9831787, 9831788, 9831789, 9831790, 9831791, 9831792, 9831793, 9831794, 9831795, 9831796, 9831797, 9831798, 9831799, 9831800, 9831801, 9831802, 9831803, 9831804, 9831805, 9831806, 9831807, 9831808, 9831809, 9831810, 9831811, 9831812, 9831813, 9831814, 9831815, 9831816, 9831817, 9831818, 9831819, 9831820, 9831821, 9831822, 9831823, 9831824, 9831825, 9831826, 9831827, 9831828, 9831829, 9831830, 9831831, 9831832, 9831833, 9831834, 9831835, 9831836, 9831837, 9831838, 9831839, 9831840, 9831841, 9831842, 9831843, 9831844, 9831845, 9831846, 9831847, 9831848, 9831849, 9831850, 9831851, 9831852, 9831853, 9831854, 9831855, 9831856, 9831857, 9831858, 9831859, 9831860, 9831861, 9831862, 9831863, 9831864, 9831865, 9831866, 9831867, 9831868, 9831869, 9831870, 9831871, 9831872, 9831873, 9831874, 9831875, 9831876, 9831877, 9831878, 9831879, 9831880, 9831881, 9831882, 9831883, 9831884, 9831885, 9831886, 9831887, 9831888, 9831889, 9831890, 9831891, 9831892, 9831893, 9831894, 9831895, 9831896, 9831897, 9831898, 9831899, 9831900, 9831901, 9831902, 9831903, 9831904, 9831905, 9831906, 9831907, 9831908, 9831909, 9831910, 9831911, 9831912, 9831913, 9831914, 9831915, 9831916, 9831917, 9831918, 9831919, 9831920, 9831921, 9831922, 9831923, 9831924, 9831925, 9831926, 9831927, 9831928, 9831929, 9831930, 9831931, 9831932, 9831933, 9831934, 9831935, 9831936, 9831937, 9831938, 9831939, 9831940, 9831941, 9831942, 9831943, 9831944, 9831945, 9831946, 9831947, 9831948, 9831949, 9831950, 9831951, 9831952, 9831953, 9831954, 9831955, 9831956, 9831957, 9831958, 9831959, 9831960, 9831961, 9831962, 9831963, 9831964, 9831965, 9831966, 9831967, 9831968, 9831969, 9831970, 9831971, 9831972, 9831973, 9831974, 9831975, 9831976, 9831977, 9831978, 9831979, 9831980, 9831981, 9831982, 9831983, 9831984, 9831985, 9831986, 9831987, 9831988, 9831989, 9831990, 9831991, 9831992, 9831993, 9831994, 9831995, 9831996, 9831997, 9831998, 9831999, 9832000, 9832001, 9832002, 9832003, 9832004, 9832005, 9832006, 9832007, 9832008, 9832009, 9832010, 9832011, 9832012, 9832013, 9832014, 9832015, 9832016, 9832017, 9832018, 9832019, 9832020, 9832021, 9832022, 9832023, 9832024, 9832025, 9832026, 9832027, 9832028, 9832029, 9832030, 9832031, 9832032, 9832033, 9832034, 9832035, 9832036, 9832037, 9832038, 9832039, 9832040, 9832041, 9832042, 9832043, 9832044, 9832045, 9832046, 9832047, 9832048, 9832049, 9832050, 9832051, 9832052, 9832053, 9832054, 9832055, 9832056, 9832057, 9832058, 9832059, 9832060, 9832061, 9832062, 9832063, 9832064, 9832065, 9832066, 9832067, 9832068, 9832069, 9832070, 9832071, 9832072, 9832073, 9832074, 9832075, 9832076, 9832077, 9832078, 9832079, 9832080, 9832081, 9832082, 9832083, 9832084, 9832085, 9832086, 9832087, 9832088, 9832089, 9832090, 9832091, 9832092, 9832093, 9832094, 9832095, 9832096, 9832097, 9832098, 9832099, 9832100, 9832101, 9832102, 9832103, 9832104, 9832105, 9832106, 9832107, 9832108, 9832109, 9832110, 9832111, 9832112, 9832113, 9832114, 9832115, 9832116, 9832117, 9832118, 9832119, 9832120, 9832121, 9832122, 9832123, 9832124, 9832125, 9832126, 9832127, 9832128, 9832129, 9832130, 9832131, 9832132, 9832133, 9832134, 9832135, 9832136, 9832137, 9832138, 9832139, 9832140, 9832141, 9832142, 9832143, 9832144, 9832145, 9832146, 9832147, 9832148, 9832149, 9832150, 9832151, 9832152, 9832153, 9832154, 9832155, 9832156, 9832157, 9832158, 9832159, 9832160, 9832161, 9832162, 9832163, 9832164, 9832165, 9832166, 9832167, 9832168, 9832169, 9832170, 9832171, 9832172, 9832173, 9832174, 9832175, 9832176, 9832177, 9832178, 9832179, 9832180, 9832181, 9832182, 9832183, 9832184, 9832185, 9832186, 9832187, 9832188, 9832189, 9832190, 9832191, 9832192, 9832193, 9832194, 9832195, 9832196, 9832197, 9832198, 9832199, 9832200, 9832201, 9832202, 9832203, 9832204, 9832205, 9832206, 9832207, 9832208, 9832209, 9832210, 9832211, 9832212, 9832213, 9832214, 9832215, 9832216, 9832217, 9832218, 9832219, 9832220, 9832221, 9832222, 9832223, 9832224, 9832225, 9832226, 9832227, 9832228, 9832229, 9832230, 9832231, 9832232, 9832233, 9832234, 9832235, 9832236, 9832237, 9832238, 9832239, 9832240, 9832241, 9832242, 9832243, 9832244, 9832245, 9832246, 9832247, 9832248, 9832249, 9832250, 9832251, 9832252, 9832253, 9832254, 9832255, 9832256, 9832257, 9832258, 9832259, 9832260, 9832261, 9832262, 9832263, 9832264, 9832265, 9832266, 9832267, 9832268, 9832269, 9832270, 9832271, 9832272, 9832273, 9832274, 9832275, 9832276, 9832277, 9832278, 9832279, 9832280, 9832281, 9832282, 9832283, 9832284, 9832285, 9832286, 9832287, 9832288, 9832289, 9832290, 9832291, 9832292, 9832293, 9832294, 9832295, 9832296, 9832297, 9832298, 9832299, 9832300, 9832301, 9832302, 9832303, 9832304, 9832305, 9832306, 9832307, 9832308, 9832309, 9832310, 9832311, 9832312, 9832313, 9832314, 9832315, 9832316, 9832317, 9832318, 9832319, 9832320, 9832321, 9832322, 9832323, 9832324, 9832325, 9832326, 9832327, 9832328, 9832329, 9832330, 9832331, 9832332, 9832333, 9832334, 9832335, 9832336, 9832337, 9832338, 9832339, 9832340, 9832341, 9832342, 9832343, 9832344, 9832345, 9832346, 9832347, 9832348, 9832349, 9832350, 9832351, 9832352, 9832353, 9832354, 9832355, 9832356, 9832357, 9832358, 9832359, 9832360, 9832361, 9832362, 9832363, 9832364, 9832365, 9832366, 9832367, 9832368, 9832369, 9832370, 9832371, 9832372, 9832373, 9832374, 9832375, 9832376, 9832377, 9832378, 9832379, 9832380, 9832381, 9832382, 9832383, 9832384, 9832385, 9832386, 9832387, 9832388, 9832389, 9832390, 9832391, 9832392, 9832393, 9832394, 9832395, 9832396, 9832397, 9832398, 9832399, 9832400, 9832401, 9832402, 9832403, 9832404, 9832405, 9832406, 9832407, 9832408, 9832409, 9832410, 9832411, 9832412, 9832413, 9832414, 9832415, 9832416, 9832417, 9832418, 9832419, 9832420, 9832421, 9832422, 9832423, 9832424, 9832425, 9832426, 9832427, 9832428, 9832429, 9832430, 9832431, 9832432, 9832433, 9832434, 9832435, 9832436, 9832437, 9832438, 9832439, 9832440, 9832441, 9832442, 9832443, 9832444, 9832445, 9832446, 9832447, 9832448, 9832449, 9832450, 9832451, 9832452, 9832453, 9832454, 9832455, 9832456, 9832457, 9832458, 9832459, 9832460, 9832461, 9832462, 9832463, 9832464, 9832465, 9832466, 9832467, 9832468, 9832469, 9832470, 9832471, 9832472, 9832473, 9832474, 9832475, 9832476, 9832477, 9832478, 9832479, 9832480, 9832481, 9832482, 9832483, 9832484, 9832485, 9832486, 9832487, 9832488, 9832489, 9832490, 9832491, 9832492, 9832493, 9832494, 9832495, 9832496, 9832497, 9832498, 9832499] |
| 完整逐局来源 | source-ledger.json |
| 冻结源码SHA | {'scripts/prism_cloud_storage_snapshot.py': 'b417e62c6aa2ce56ad2968ab0ac4c952b4a954514128a6923efc272129f5eb8c', 'scripts/prism_dsw_arena.py': '172b6f9edbb69b2d0fc139cd3ac4678d5f0392f97b59ebd09164467beda7b399', 'scripts/prism_match_details.py': '0f7fb79de0a65e60dfcb914716c99562fa44dd7673e6c1c0ea5ee4916ba11bc4', 'scripts/prism_notebook_arena.py': '84baf17c3e9fb31638bb5e56799ceffaec41b96a7a358b289023ab55a6f7b935', 'scripts/prism_notebook_report.py': 'bc7dd35146d795c28c8f8a7fb3910cfe3b832e88884de32b93a0d010ff6fd9ec', 'scripts/prism_ppo_fixed_eval.py': 'fb6683d0f0d91d92efafef1d136545b3dabf376e014e066b19beb43fe78aeacb'} |




## M67种子B最终c20未发布训练检查点 对阵 Prism Alpha v0.1.4



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 2981/54/1965 | 59.6200% | 60.1600% | 58.2600% / 60.9400% | 58.8200% / 61.4900% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1536/22/942 | 61.4400 | 61.8800 | 14.6252 | 13.5600 |
| P1（后手） | 2500 | 1445/32/1023 | 57.8000 | 58.4400 | 14.6136 | 13.6296 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.6194 | 13.5948 |
| VP/本人全部决策 | 0.5438 | 0.5056 |
| VP/本人Main | 0.5438 | 0.5057 |
| VP/全局ply | 0.2719 | 0.2528 |
| 永久折扣/购卡每局 | 11.7878 | 11.8892 |
| 贵族/局 | 0.4832 | 0.4442 |
| 获得贵族的对局% | 40.1200 | 36.6000 |
| 预留获取/局 | 3.3590 | 3.2838 |
| 预留买回/局 | 1.3896 | 1.3266 |
| 终局未买回预留/局 | 1.9694 | 1.9572 |
| 预留买回/获取%（总分母） | 41.3695 | 40.3983 |
| 购入0 VP卡/局 | 5.9290 | 6.2578 |
| 购入1 VP卡/局 | 2.0530 | 2.0424 |
| 购入2 VP卡/局 | 1.8440 | 1.7798 |
| 购入3 VP卡/局 | 0.7952 | 0.8486 |
| 购入4 VP卡/局 | 0.7898 | 0.6886 |
| 购入5 VP卡/局 | 0.3768 | 0.2720 |
| White折扣/局 | 2.4474 | 2.3564 |
| Blue折扣/局 | 2.1280 | 2.3570 |
| Green折扣/局 | 2.2384 | 2.4326 |
| Red折扣/局 | 2.5404 | 2.3050 |
| Black折扣/局 | 2.4336 | 2.4382 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 51991 / 38.6749% | 52813 / 39.2819% |
| buy_reserved | 6948 / 5.1685% | 6633 / 4.9336% |
| take_tokens | 58671 / 43.6440% | 58541 / 43.5424% |
| reserve_market | 16794 / 12.4927% | 16419 / 12.2123% |
| reserve_deck | 1 / 0.0007% | 0 / 0.0000% |
| choose_noble | 24 / 0.0179% | 39 / 0.0290% |
| pass | 2 / 0.0015% | 1 / 0.0007% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 268877 / 53.7754 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.8938 / 19.0000 / 27.0000 / 108.0000 / 2.1512 |
| Main轮均值 | 26.8814 |
| 绝对终局分差 | 3.6110 |
| 分差≤2对局% | 35.3200 |
| 对局监督墙钟秒：累计 / 均 / P95 | 2766.1492 / 0.5532 / 0.8062 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', 'sha256': 'e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/alpha.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/alpha.json', 'sha256': 'd3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




## M67种子B最终c20未发布训练检查点 对阵 Prism Balance v0.1.0



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 2983/46/1971 | 59.6600% | 60.1200% | 58.3200% / 61.0200% | 58.7900% / 61.4700% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1525/29/946 | 61.0000 | 61.5800 | 14.6120 | 13.6248 |
| P1（后手） | 2500 | 1458/17/1025 | 58.3200 | 58.6600 | 14.5692 | 13.5464 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.5906 | 13.5856 |
| VP/本人全部决策 | 0.5418 | 0.5045 |
| VP/本人Main | 0.5419 | 0.5046 |
| VP/全局ply | 0.2709 | 0.2522 |
| 永久折扣/购卡每局 | 11.7894 | 11.9156 |
| 贵族/局 | 0.4726 | 0.4528 |
| 获得贵族的对局% | 39.5200 | 36.8600 |
| 预留获取/局 | 3.3636 | 3.3154 |
| 预留买回/局 | 1.3968 | 1.3138 |
| 终局未买回预留/局 | 1.9668 | 2.0016 |
| 预留买回/获取%（总分母） | 41.5269 | 39.6272 |
| 购入0 VP卡/局 | 5.9340 | 6.1862 |
| 购入1 VP卡/局 | 2.0346 | 2.1568 |
| 购入2 VP卡/局 | 1.8576 | 1.8162 |
| 购入3 VP卡/局 | 0.8074 | 0.8372 |
| 购入4 VP卡/局 | 0.7782 | 0.6696 |
| 购入5 VP卡/局 | 0.3776 | 0.2496 |
| White折扣/局 | 2.4106 | 2.4190 |
| Blue折扣/局 | 2.1534 | 2.3616 |
| Green折扣/局 | 2.2764 | 2.3726 |
| Red折扣/局 | 2.5196 | 2.3158 |
| Black折扣/局 | 2.4294 | 2.4466 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 51963 / 38.5937% | 53009 / 39.3686% |
| buy_reserved | 6984 / 5.1871% | 6569 / 4.8786% |
| take_tokens | 58842 / 43.7029% | 58458 / 43.4154% |
| reserve_market | 16817 / 12.4903% | 16576 / 12.3106% |
| reserve_deck | 1 / 0.0007% | 1 / 0.0007% |
| choose_noble | 28 / 0.0208% | 35 / 0.0260% |
| pass | 6 / 0.0045% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 269289 / 53.8578 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.9346 / 19.0000 / 27.0000 / 260.0000 / 3.9376 |
| Main轮均值 | 26.9226 |
| 绝对终局分差 | 3.6190 |
| 分差≤2对局% | 35.1800 |
| 对局监督墙钟秒：累计 / 均 / P95 | 2770.9138 / 0.5542 / 0.8049 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', 'sha256': 'e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/balance.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/balance.json', 'sha256': '225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




## M67种子B最终c20未发布训练检查点 对阵 Prism Beta v0.1.0



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 2888/51/2061 | 57.7600% | 58.2700% | 56.4600% / 59.0400% | 56.9700% / 59.5500% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1536/26/938 | 61.4400 | 61.9600 | 14.6152 | 13.6956 |
| P1（后手） | 2500 | 1352/25/1123 | 54.0800 | 54.5800 | 14.4448 | 13.7956 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.5300 | 13.7456 |
| VP/本人全部决策 | 0.5397 | 0.5106 |
| VP/本人Main | 0.5398 | 0.5107 |
| VP/全局ply | 0.2699 | 0.2553 |
| 永久折扣/购卡每局 | 11.8332 | 11.8092 |
| 贵族/局 | 0.4904 | 0.4482 |
| 获得贵族的对局% | 40.7200 | 37.0800 |
| 预留获取/局 | 3.3392 | 3.5566 |
| 预留买回/局 | 1.3796 | 1.4440 |
| 终局未买回预留/局 | 1.9596 | 2.1126 |
| 预留买回/获取%（总分母） | 41.3153 | 40.6006 |
| 购入0 VP卡/局 | 5.9874 | 6.0836 |
| 购入1 VP卡/局 | 2.0612 | 2.1150 |
| 购入2 VP卡/局 | 1.8472 | 1.8100 |
| 购入3 VP卡/局 | 0.8120 | 0.8244 |
| 购入4 VP卡/局 | 0.7598 | 0.6882 |
| 购入5 VP卡/局 | 0.3656 | 0.2880 |
| White折扣/局 | 2.4528 | 2.3860 |
| Blue折扣/局 | 2.1838 | 2.3006 |
| Green折扣/局 | 2.2888 | 2.3352 |
| Red折扣/局 | 2.4838 | 2.3576 |
| Black折扣/局 | 2.4240 | 2.4298 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 52268 / 38.8257% | 51826 / 38.5037% |
| buy_reserved | 6898 / 5.1240% | 7220 / 5.3640% |
| take_tokens | 58719 / 43.6177% | 57752 / 42.9064% |
| reserve_market | 16695 / 12.4014% | 17780 / 13.2095% |
| reserve_deck | 1 / 0.0007% | 3 / 0.0022% |
| choose_noble | 41 / 0.0305% | 19 / 0.0141% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 269222 / 53.8444 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.9282 / 20.0000 / 27.0000 / 33.0000 / 1.7766 |
| Main轮均值 | 26.9162 |
| 绝对终局分差 | 3.5888 |
| 分差≤2对局% | 36.0000 |
| 对局监督墙钟秒：累计 / 均 / P95 | 2742.6021 / 0.5485 / 0.7963 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', 'sha256': 'e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/beta.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/beta.json', 'sha256': '69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




## M67种子B最终c20未发布训练检查点 对阵 Prism v0.1.1



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 3535/45/1420 | 70.7000% | 71.1500% | 69.4200% / 71.9600% | 69.8900% / 72.4000% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 1778/26/696 | 71.1200 | 71.6400 | 15.0376 | 12.9024 |
| P1（后手） | 2500 | 1757/19/724 | 70.2800 | 70.6600 | 15.0828 | 12.8960 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 15.0602 | 12.8992 |
| VP/本人全部决策 | 0.5654 | 0.4841 |
| VP/本人Main | 0.5654 | 0.4843 |
| VP/全局ply | 0.2826 | 0.2421 |
| 永久折扣/购卡每局 | 11.7484 | 12.3570 |
| 贵族/局 | 0.4632 | 0.4852 |
| 获得贵族的对局% | 39.0000 | 38.6800 |
| 预留获取/局 | 3.1348 | 2.6614 |
| 预留买回/局 | 1.2694 | 1.1192 |
| 终局未买回预留/局 | 1.8654 | 1.5422 |
| 预留买回/获取%（总分母） | 40.4938 | 42.0531 |
| 购入0 VP卡/局 | 5.8212 | 6.6894 |
| 购入1 VP卡/局 | 1.9392 | 2.3198 |
| 购入2 VP卡/局 | 1.9126 | 1.8074 |
| 购入3 VP卡/局 | 0.8178 | 0.8334 |
| 购入4 VP卡/局 | 0.8352 | 0.5262 |
| 购入5 VP卡/局 | 0.4224 | 0.1808 |
| White折扣/局 | 2.4352 | 2.4484 |
| Blue折扣/局 | 2.0634 | 2.6164 |
| Green折扣/局 | 2.2310 | 2.4772 |
| Red折扣/局 | 2.5240 | 2.4040 |
| Black折扣/局 | 2.4948 | 2.4110 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 52395 / 39.3379% | 56189 / 42.1760% |
| buy_reserved | 6347 / 4.7653% | 5596 / 4.2004% |
| take_tokens | 58757 / 44.1145% | 58081 / 43.5962% |
| reserve_market | 15674 / 11.7680% | 13307 / 9.9884% |
| reserve_deck | 0 / 0.0000% | 0 / 0.0000% |
| choose_noble | 19 / 0.0143% | 52 / 0.0390% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 266417 / 53.2834 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.6486 / 19.0000 / 27.0000 / 33.0000 / 1.8240 |
| Main轮均值 | 26.6346 |
| 绝对终局分差 | 3.9070 |
| 分差≤2对局% | 32.9800 |
| 对局监督墙钟秒：累计 / 均 / P95 | 2641.7812 / 0.5284 / 0.7720 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', 'sha256': 'e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/general.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/general.json', 'sha256': 'a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




## M67种子B最终c20未发布训练检查点 对阵 Heuristic v0.3.1



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 4213/21/766 | 84.2600% | 84.4700% | 83.2400% / 85.2600% | 83.4600% / 85.4600% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 2144/10/346 | 85.7600 | 85.9600 | 15.6172 | 11.5924 |
| P1（后手） | 2500 | 2069/11/420 | 82.7600 | 82.9800 | 15.5540 | 11.6692 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 15.5856 | 11.6308 |
| VP/本人全部决策 | 0.5946 | 0.4435 |
| VP/本人Main | 0.5947 | 0.4438 |
| VP/全局ply | 0.2972 | 0.2218 |
| 永久折扣/购卡每局 | 11.6910 | 12.7372 |
| 贵族/局 | 0.4326 | 0.5494 |
| 获得贵族的对局% | 37.0000 | 41.3000 |
| 预留获取/局 | 2.6632 | 2.5334 |
| 预留买回/局 | 1.0946 | 1.3210 |
| 终局未买回预留/局 | 1.5686 | 1.2124 |
| 预留买回/获取%（总分母） | 41.1009 | 52.1434 |
| 购入0 VP卡/局 | 5.7064 | 7.3374 |
| 购入1 VP卡/局 | 1.8604 | 2.5584 |
| 购入2 VP卡/局 | 1.8884 | 1.6438 |
| 购入3 VP卡/局 | 0.8108 | 0.7410 |
| 购入4 VP卡/局 | 0.9068 | 0.3694 |
| 购入5 VP卡/局 | 0.5182 | 0.0872 |
| White折扣/局 | 2.4168 | 2.5202 |
| Blue折扣/局 | 2.1286 | 2.6440 |
| Green折扣/局 | 2.2284 | 2.5802 |
| Red折扣/局 | 2.4860 | 2.5084 |
| Black折扣/局 | 2.4312 | 2.4844 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 52982 / 40.4267% | 57081 / 43.5337% |
| buy_reserved | 5473 / 4.1760% | 6605 / 5.0374% |
| take_tokens | 59268 / 45.2231% | 54686 / 41.7072% |
| reserve_market | 13315 / 10.1597% | 12573 / 9.5890% |
| reserve_deck | 1 / 0.0008% | 94 / 0.0717% |
| choose_noble | 18 / 0.0137% | 80 / 0.0610% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 262176 / 52.4352 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.2270 / 20.0000 / 26.0000 / 33.0000 / 1.8147 |
| Main轮均值 | 26.2078 |
| 绝对终局分差 | 4.7972 |
| 分差≤2对局% | 22.7400 |
| 对局监督墙钟秒：累计 / 均 / P95 | 1634.9213 / 0.3270 / 0.4954 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', 'sha256': 'e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-heuristic-v02', '--seed', '67020001'], 'files': [], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




## M67种子B最终c20未发布训练检查点 对阵 Prism v0.1.0



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 5000/2500 | 4213/16/771 | 84.2600% | 84.4200% | 83.2400% / 85.2600% | 83.4000% / 85.4200% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2500 | 2157/12/331 | 86.2800 | 86.5200 | 15.5460 | 11.4596 |
| P1（后手） | 2500 | 2056/4/440 | 82.2400 | 82.3200 | 15.3964 | 11.7068 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 15.4712 | 11.5832 |
| VP/本人全部决策 | 0.5907 | 0.4421 |
| VP/本人Main | 0.5908 | 0.4423 |
| VP/全局ply | 0.2953 | 0.2211 |
| 永久折扣/购卡每局 | 11.6460 | 12.8050 |
| 贵族/局 | 0.4462 | 0.5116 |
| 获得贵族的对局% | 38.1600 | 38.5600 |
| 预留获取/局 | 2.7472 | 2.0310 |
| 预留买回/局 | 1.1218 | 1.0238 |
| 终局未买回预留/局 | 1.6254 | 1.0072 |
| 预留买回/获取%（总分母） | 40.8343 | 50.4087 |
| 购入0 VP卡/局 | 5.6534 | 7.3860 |
| 购入1 VP卡/局 | 1.8824 | 2.5556 |
| 购入2 VP卡/局 | 1.9158 | 1.6570 |
| 购入3 VP卡/局 | 0.8262 | 0.7488 |
| 购入4 VP卡/局 | 0.9010 | 0.3556 |
| 购入5 VP卡/局 | 0.4672 | 0.1020 |
| White折扣/局 | 2.3972 | 2.5328 |
| Blue折扣/局 | 2.0364 | 2.7430 |
| Green折扣/局 | 2.2470 | 2.5442 |
| Red折扣/局 | 2.5326 | 2.4156 |
| Black折扣/局 | 2.4328 | 2.5694 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 52621 / 40.1825% | 58906 / 44.9633% |
| buy_reserved | 5609 / 4.2832% | 5119 / 3.9074% |
| take_tokens | 58967 / 45.0284% | 56754 / 43.3207% |
| reserve_market | 13736 / 10.4891% | 10130 / 7.7323% |
| reserve_deck | 0 / 0.0000% | 25 / 0.0191% |
| choose_noble | 21 / 0.0160% | 75 / 0.0572% |
| pass | 1 / 0.0008% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 261964 / 52.3928 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.2058 / 20.0000 / 26.0000 / 35.0000 / 1.8730 |
| Main轮均值 | 26.1868 |
| 绝对终局分差 | 4.8096 |
| 分差≤2对局% | 22.4800 |
| 对局监督墙钟秒：累计 / 均 / P95 | 2508.0787 / 0.5016 / 0.7272 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', 'sha256': 'e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/initial.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/initial.json', 'sha256': '5db70b773083858b83c6e679d5641f1b78d4c5fbe34c48950cc906064f821b54'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |



# a-direct 原始完整报告

# Prism 通用对战结果（DSW / SSH）



**产物：已完成全部固定网格，Rust规则回放验核与双方指标守恒通过。**



**竞技：DEVELOPMENT_ONLY_NOT_PROMOTED。**这是独立通用开发测量，没有执行任何里程碑正式晋级门。



**风格：描述性数据。**不凭单一更高/更低经济指标授予风格身份。



候选按用户声明的完整模型名及导出SHA识别，未发布检查点仍须在名称中明确标注。每对手恰好双座种子块；个人表按模型身份归并，物理P0不总是候选。



## 候选匹配比较



只有一个候选，匹配基线到候选比较NOT_APPLICABLE。

↑/↓仅为方向标记，不表示更好或差异显著。下面CI为逐对手描述性双座bootstrap；不做多门验收或发布。若只有一个种子块，CI退化，不能据此确认稳定性。



## 总体执行与来源



| 字段 | 记录 |
| --- | --- |
| 固定局数 | 10000 |
| 并发进程 / 每进程库线程 | 4 / 1 |
| 累计已测活动墙钟秒（至报告前监测点） | 2129.3555 |
| 首次派发至报告生成秒（包含暂停） | 2172.3806 |
| 时钟范围 | standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download |
| 资源监控 | observed process-tree soft limits; shared platform cgroups are not owned |
| 已测负载 | {'observed_processes': 2, 'peak_observed_rss_bytes': 234627072, 'process_tree_cpu_seconds': 6472.35, 'process_tree_rss_sum_bytes': 37031936, 'scope': 'sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages'} |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |
| 配置SHA256 | ec9807ae2f24df70a831e206748f951a710d768b45abb548c300276ac824aae7 |
| plan SHA256 | f7ad2c5df84e0c350daa63e868a099366fbd084d896d69ecf8c7716ee89ab09e |
| engine SHA256 | 6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f |
| metrics SHA256 | 39c630d5e0a9e0611ca4ec8c8b2e4a78817bf971c7bdc7446b614035aedbcb37 |
| Git基线 / 源码dirty | NOT_AVAILABLE / None |
| Bootstrap | {'kind': 'descriptive paired seed blocks, not acceptance', 'samples': 20000, 'seed': 64049999} |
| 种子 | [9840000, 9840001, 9840002, 9840003, 9840004, 9840005, 9840006, 9840007, 9840008, 9840009, 9840010, 9840011, 9840012, 9840013, 9840014, 9840015, 9840016, 9840017, 9840018, 9840019, 9840020, 9840021, 9840022, 9840023, 9840024, 9840025, 9840026, 9840027, 9840028, 9840029, 9840030, 9840031, 9840032, 9840033, 9840034, 9840035, 9840036, 9840037, 9840038, 9840039, 9840040, 9840041, 9840042, 9840043, 9840044, 9840045, 9840046, 9840047, 9840048, 9840049, 9840050, 9840051, 9840052, 9840053, 9840054, 9840055, 9840056, 9840057, 9840058, 9840059, 9840060, 9840061, 9840062, 9840063, 9840064, 9840065, 9840066, 9840067, 9840068, 9840069, 9840070, 9840071, 9840072, 9840073, 9840074, 9840075, 9840076, 9840077, 9840078, 9840079, 9840080, 9840081, 9840082, 9840083, 9840084, 9840085, 9840086, 9840087, 9840088, 9840089, 9840090, 9840091, 9840092, 9840093, 9840094, 9840095, 9840096, 9840097, 9840098, 9840099, 9840100, 9840101, 9840102, 9840103, 9840104, 9840105, 9840106, 9840107, 9840108, 9840109, 9840110, 9840111, 9840112, 9840113, 9840114, 9840115, 9840116, 9840117, 9840118, 9840119, 9840120, 9840121, 9840122, 9840123, 9840124, 9840125, 9840126, 9840127, 9840128, 9840129, 9840130, 9840131, 9840132, 9840133, 9840134, 9840135, 9840136, 9840137, 9840138, 9840139, 9840140, 9840141, 9840142, 9840143, 9840144, 9840145, 9840146, 9840147, 9840148, 9840149, 9840150, 9840151, 9840152, 9840153, 9840154, 9840155, 9840156, 9840157, 9840158, 9840159, 9840160, 9840161, 9840162, 9840163, 9840164, 9840165, 9840166, 9840167, 9840168, 9840169, 9840170, 9840171, 9840172, 9840173, 9840174, 9840175, 9840176, 9840177, 9840178, 9840179, 9840180, 9840181, 9840182, 9840183, 9840184, 9840185, 9840186, 9840187, 9840188, 9840189, 9840190, 9840191, 9840192, 9840193, 9840194, 9840195, 9840196, 9840197, 9840198, 9840199, 9840200, 9840201, 9840202, 9840203, 9840204, 9840205, 9840206, 9840207, 9840208, 9840209, 9840210, 9840211, 9840212, 9840213, 9840214, 9840215, 9840216, 9840217, 9840218, 9840219, 9840220, 9840221, 9840222, 9840223, 9840224, 9840225, 9840226, 9840227, 9840228, 9840229, 9840230, 9840231, 9840232, 9840233, 9840234, 9840235, 9840236, 9840237, 9840238, 9840239, 9840240, 9840241, 9840242, 9840243, 9840244, 9840245, 9840246, 9840247, 9840248, 9840249, 9840250, 9840251, 9840252, 9840253, 9840254, 9840255, 9840256, 9840257, 9840258, 9840259, 9840260, 9840261, 9840262, 9840263, 9840264, 9840265, 9840266, 9840267, 9840268, 9840269, 9840270, 9840271, 9840272, 9840273, 9840274, 9840275, 9840276, 9840277, 9840278, 9840279, 9840280, 9840281, 9840282, 9840283, 9840284, 9840285, 9840286, 9840287, 9840288, 9840289, 9840290, 9840291, 9840292, 9840293, 9840294, 9840295, 9840296, 9840297, 9840298, 9840299, 9840300, 9840301, 9840302, 9840303, 9840304, 9840305, 9840306, 9840307, 9840308, 9840309, 9840310, 9840311, 9840312, 9840313, 9840314, 9840315, 9840316, 9840317, 9840318, 9840319, 9840320, 9840321, 9840322, 9840323, 9840324, 9840325, 9840326, 9840327, 9840328, 9840329, 9840330, 9840331, 9840332, 9840333, 9840334, 9840335, 9840336, 9840337, 9840338, 9840339, 9840340, 9840341, 9840342, 9840343, 9840344, 9840345, 9840346, 9840347, 9840348, 9840349, 9840350, 9840351, 9840352, 9840353, 9840354, 9840355, 9840356, 9840357, 9840358, 9840359, 9840360, 9840361, 9840362, 9840363, 9840364, 9840365, 9840366, 9840367, 9840368, 9840369, 9840370, 9840371, 9840372, 9840373, 9840374, 9840375, 9840376, 9840377, 9840378, 9840379, 9840380, 9840381, 9840382, 9840383, 9840384, 9840385, 9840386, 9840387, 9840388, 9840389, 9840390, 9840391, 9840392, 9840393, 9840394, 9840395, 9840396, 9840397, 9840398, 9840399, 9840400, 9840401, 9840402, 9840403, 9840404, 9840405, 9840406, 9840407, 9840408, 9840409, 9840410, 9840411, 9840412, 9840413, 9840414, 9840415, 9840416, 9840417, 9840418, 9840419, 9840420, 9840421, 9840422, 9840423, 9840424, 9840425, 9840426, 9840427, 9840428, 9840429, 9840430, 9840431, 9840432, 9840433, 9840434, 9840435, 9840436, 9840437, 9840438, 9840439, 9840440, 9840441, 9840442, 9840443, 9840444, 9840445, 9840446, 9840447, 9840448, 9840449, 9840450, 9840451, 9840452, 9840453, 9840454, 9840455, 9840456, 9840457, 9840458, 9840459, 9840460, 9840461, 9840462, 9840463, 9840464, 9840465, 9840466, 9840467, 9840468, 9840469, 9840470, 9840471, 9840472, 9840473, 9840474, 9840475, 9840476, 9840477, 9840478, 9840479, 9840480, 9840481, 9840482, 9840483, 9840484, 9840485, 9840486, 9840487, 9840488, 9840489, 9840490, 9840491, 9840492, 9840493, 9840494, 9840495, 9840496, 9840497, 9840498, 9840499, 9840500, 9840501, 9840502, 9840503, 9840504, 9840505, 9840506, 9840507, 9840508, 9840509, 9840510, 9840511, 9840512, 9840513, 9840514, 9840515, 9840516, 9840517, 9840518, 9840519, 9840520, 9840521, 9840522, 9840523, 9840524, 9840525, 9840526, 9840527, 9840528, 9840529, 9840530, 9840531, 9840532, 9840533, 9840534, 9840535, 9840536, 9840537, 9840538, 9840539, 9840540, 9840541, 9840542, 9840543, 9840544, 9840545, 9840546, 9840547, 9840548, 9840549, 9840550, 9840551, 9840552, 9840553, 9840554, 9840555, 9840556, 9840557, 9840558, 9840559, 9840560, 9840561, 9840562, 9840563, 9840564, 9840565, 9840566, 9840567, 9840568, 9840569, 9840570, 9840571, 9840572, 9840573, 9840574, 9840575, 9840576, 9840577, 9840578, 9840579, 9840580, 9840581, 9840582, 9840583, 9840584, 9840585, 9840586, 9840587, 9840588, 9840589, 9840590, 9840591, 9840592, 9840593, 9840594, 9840595, 9840596, 9840597, 9840598, 9840599, 9840600, 9840601, 9840602, 9840603, 9840604, 9840605, 9840606, 9840607, 9840608, 9840609, 9840610, 9840611, 9840612, 9840613, 9840614, 9840615, 9840616, 9840617, 9840618, 9840619, 9840620, 9840621, 9840622, 9840623, 9840624, 9840625, 9840626, 9840627, 9840628, 9840629, 9840630, 9840631, 9840632, 9840633, 9840634, 9840635, 9840636, 9840637, 9840638, 9840639, 9840640, 9840641, 9840642, 9840643, 9840644, 9840645, 9840646, 9840647, 9840648, 9840649, 9840650, 9840651, 9840652, 9840653, 9840654, 9840655, 9840656, 9840657, 9840658, 9840659, 9840660, 9840661, 9840662, 9840663, 9840664, 9840665, 9840666, 9840667, 9840668, 9840669, 9840670, 9840671, 9840672, 9840673, 9840674, 9840675, 9840676, 9840677, 9840678, 9840679, 9840680, 9840681, 9840682, 9840683, 9840684, 9840685, 9840686, 9840687, 9840688, 9840689, 9840690, 9840691, 9840692, 9840693, 9840694, 9840695, 9840696, 9840697, 9840698, 9840699, 9840700, 9840701, 9840702, 9840703, 9840704, 9840705, 9840706, 9840707, 9840708, 9840709, 9840710, 9840711, 9840712, 9840713, 9840714, 9840715, 9840716, 9840717, 9840718, 9840719, 9840720, 9840721, 9840722, 9840723, 9840724, 9840725, 9840726, 9840727, 9840728, 9840729, 9840730, 9840731, 9840732, 9840733, 9840734, 9840735, 9840736, 9840737, 9840738, 9840739, 9840740, 9840741, 9840742, 9840743, 9840744, 9840745, 9840746, 9840747, 9840748, 9840749, 9840750, 9840751, 9840752, 9840753, 9840754, 9840755, 9840756, 9840757, 9840758, 9840759, 9840760, 9840761, 9840762, 9840763, 9840764, 9840765, 9840766, 9840767, 9840768, 9840769, 9840770, 9840771, 9840772, 9840773, 9840774, 9840775, 9840776, 9840777, 9840778, 9840779, 9840780, 9840781, 9840782, 9840783, 9840784, 9840785, 9840786, 9840787, 9840788, 9840789, 9840790, 9840791, 9840792, 9840793, 9840794, 9840795, 9840796, 9840797, 9840798, 9840799, 9840800, 9840801, 9840802, 9840803, 9840804, 9840805, 9840806, 9840807, 9840808, 9840809, 9840810, 9840811, 9840812, 9840813, 9840814, 9840815, 9840816, 9840817, 9840818, 9840819, 9840820, 9840821, 9840822, 9840823, 9840824, 9840825, 9840826, 9840827, 9840828, 9840829, 9840830, 9840831, 9840832, 9840833, 9840834, 9840835, 9840836, 9840837, 9840838, 9840839, 9840840, 9840841, 9840842, 9840843, 9840844, 9840845, 9840846, 9840847, 9840848, 9840849, 9840850, 9840851, 9840852, 9840853, 9840854, 9840855, 9840856, 9840857, 9840858, 9840859, 9840860, 9840861, 9840862, 9840863, 9840864, 9840865, 9840866, 9840867, 9840868, 9840869, 9840870, 9840871, 9840872, 9840873, 9840874, 9840875, 9840876, 9840877, 9840878, 9840879, 9840880, 9840881, 9840882, 9840883, 9840884, 9840885, 9840886, 9840887, 9840888, 9840889, 9840890, 9840891, 9840892, 9840893, 9840894, 9840895, 9840896, 9840897, 9840898, 9840899, 9840900, 9840901, 9840902, 9840903, 9840904, 9840905, 9840906, 9840907, 9840908, 9840909, 9840910, 9840911, 9840912, 9840913, 9840914, 9840915, 9840916, 9840917, 9840918, 9840919, 9840920, 9840921, 9840922, 9840923, 9840924, 9840925, 9840926, 9840927, 9840928, 9840929, 9840930, 9840931, 9840932, 9840933, 9840934, 9840935, 9840936, 9840937, 9840938, 9840939, 9840940, 9840941, 9840942, 9840943, 9840944, 9840945, 9840946, 9840947, 9840948, 9840949, 9840950, 9840951, 9840952, 9840953, 9840954, 9840955, 9840956, 9840957, 9840958, 9840959, 9840960, 9840961, 9840962, 9840963, 9840964, 9840965, 9840966, 9840967, 9840968, 9840969, 9840970, 9840971, 9840972, 9840973, 9840974, 9840975, 9840976, 9840977, 9840978, 9840979, 9840980, 9840981, 9840982, 9840983, 9840984, 9840985, 9840986, 9840987, 9840988, 9840989, 9840990, 9840991, 9840992, 9840993, 9840994, 9840995, 9840996, 9840997, 9840998, 9840999, 9841000, 9841001, 9841002, 9841003, 9841004, 9841005, 9841006, 9841007, 9841008, 9841009, 9841010, 9841011, 9841012, 9841013, 9841014, 9841015, 9841016, 9841017, 9841018, 9841019, 9841020, 9841021, 9841022, 9841023, 9841024, 9841025, 9841026, 9841027, 9841028, 9841029, 9841030, 9841031, 9841032, 9841033, 9841034, 9841035, 9841036, 9841037, 9841038, 9841039, 9841040, 9841041, 9841042, 9841043, 9841044, 9841045, 9841046, 9841047, 9841048, 9841049, 9841050, 9841051, 9841052, 9841053, 9841054, 9841055, 9841056, 9841057, 9841058, 9841059, 9841060, 9841061, 9841062, 9841063, 9841064, 9841065, 9841066, 9841067, 9841068, 9841069, 9841070, 9841071, 9841072, 9841073, 9841074, 9841075, 9841076, 9841077, 9841078, 9841079, 9841080, 9841081, 9841082, 9841083, 9841084, 9841085, 9841086, 9841087, 9841088, 9841089, 9841090, 9841091, 9841092, 9841093, 9841094, 9841095, 9841096, 9841097, 9841098, 9841099, 9841100, 9841101, 9841102, 9841103, 9841104, 9841105, 9841106, 9841107, 9841108, 9841109, 9841110, 9841111, 9841112, 9841113, 9841114, 9841115, 9841116, 9841117, 9841118, 9841119, 9841120, 9841121, 9841122, 9841123, 9841124, 9841125, 9841126, 9841127, 9841128, 9841129, 9841130, 9841131, 9841132, 9841133, 9841134, 9841135, 9841136, 9841137, 9841138, 9841139, 9841140, 9841141, 9841142, 9841143, 9841144, 9841145, 9841146, 9841147, 9841148, 9841149, 9841150, 9841151, 9841152, 9841153, 9841154, 9841155, 9841156, 9841157, 9841158, 9841159, 9841160, 9841161, 9841162, 9841163, 9841164, 9841165, 9841166, 9841167, 9841168, 9841169, 9841170, 9841171, 9841172, 9841173, 9841174, 9841175, 9841176, 9841177, 9841178, 9841179, 9841180, 9841181, 9841182, 9841183, 9841184, 9841185, 9841186, 9841187, 9841188, 9841189, 9841190, 9841191, 9841192, 9841193, 9841194, 9841195, 9841196, 9841197, 9841198, 9841199, 9841200, 9841201, 9841202, 9841203, 9841204, 9841205, 9841206, 9841207, 9841208, 9841209, 9841210, 9841211, 9841212, 9841213, 9841214, 9841215, 9841216, 9841217, 9841218, 9841219, 9841220, 9841221, 9841222, 9841223, 9841224, 9841225, 9841226, 9841227, 9841228, 9841229, 9841230, 9841231, 9841232, 9841233, 9841234, 9841235, 9841236, 9841237, 9841238, 9841239, 9841240, 9841241, 9841242, 9841243, 9841244, 9841245, 9841246, 9841247, 9841248, 9841249, 9841250, 9841251, 9841252, 9841253, 9841254, 9841255, 9841256, 9841257, 9841258, 9841259, 9841260, 9841261, 9841262, 9841263, 9841264, 9841265, 9841266, 9841267, 9841268, 9841269, 9841270, 9841271, 9841272, 9841273, 9841274, 9841275, 9841276, 9841277, 9841278, 9841279, 9841280, 9841281, 9841282, 9841283, 9841284, 9841285, 9841286, 9841287, 9841288, 9841289, 9841290, 9841291, 9841292, 9841293, 9841294, 9841295, 9841296, 9841297, 9841298, 9841299, 9841300, 9841301, 9841302, 9841303, 9841304, 9841305, 9841306, 9841307, 9841308, 9841309, 9841310, 9841311, 9841312, 9841313, 9841314, 9841315, 9841316, 9841317, 9841318, 9841319, 9841320, 9841321, 9841322, 9841323, 9841324, 9841325, 9841326, 9841327, 9841328, 9841329, 9841330, 9841331, 9841332, 9841333, 9841334, 9841335, 9841336, 9841337, 9841338, 9841339, 9841340, 9841341, 9841342, 9841343, 9841344, 9841345, 9841346, 9841347, 9841348, 9841349, 9841350, 9841351, 9841352, 9841353, 9841354, 9841355, 9841356, 9841357, 9841358, 9841359, 9841360, 9841361, 9841362, 9841363, 9841364, 9841365, 9841366, 9841367, 9841368, 9841369, 9841370, 9841371, 9841372, 9841373, 9841374, 9841375, 9841376, 9841377, 9841378, 9841379, 9841380, 9841381, 9841382, 9841383, 9841384, 9841385, 9841386, 9841387, 9841388, 9841389, 9841390, 9841391, 9841392, 9841393, 9841394, 9841395, 9841396, 9841397, 9841398, 9841399, 9841400, 9841401, 9841402, 9841403, 9841404, 9841405, 9841406, 9841407, 9841408, 9841409, 9841410, 9841411, 9841412, 9841413, 9841414, 9841415, 9841416, 9841417, 9841418, 9841419, 9841420, 9841421, 9841422, 9841423, 9841424, 9841425, 9841426, 9841427, 9841428, 9841429, 9841430, 9841431, 9841432, 9841433, 9841434, 9841435, 9841436, 9841437, 9841438, 9841439, 9841440, 9841441, 9841442, 9841443, 9841444, 9841445, 9841446, 9841447, 9841448, 9841449, 9841450, 9841451, 9841452, 9841453, 9841454, 9841455, 9841456, 9841457, 9841458, 9841459, 9841460, 9841461, 9841462, 9841463, 9841464, 9841465, 9841466, 9841467, 9841468, 9841469, 9841470, 9841471, 9841472, 9841473, 9841474, 9841475, 9841476, 9841477, 9841478, 9841479, 9841480, 9841481, 9841482, 9841483, 9841484, 9841485, 9841486, 9841487, 9841488, 9841489, 9841490, 9841491, 9841492, 9841493, 9841494, 9841495, 9841496, 9841497, 9841498, 9841499, 9841500, 9841501, 9841502, 9841503, 9841504, 9841505, 9841506, 9841507, 9841508, 9841509, 9841510, 9841511, 9841512, 9841513, 9841514, 9841515, 9841516, 9841517, 9841518, 9841519, 9841520, 9841521, 9841522, 9841523, 9841524, 9841525, 9841526, 9841527, 9841528, 9841529, 9841530, 9841531, 9841532, 9841533, 9841534, 9841535, 9841536, 9841537, 9841538, 9841539, 9841540, 9841541, 9841542, 9841543, 9841544, 9841545, 9841546, 9841547, 9841548, 9841549, 9841550, 9841551, 9841552, 9841553, 9841554, 9841555, 9841556, 9841557, 9841558, 9841559, 9841560, 9841561, 9841562, 9841563, 9841564, 9841565, 9841566, 9841567, 9841568, 9841569, 9841570, 9841571, 9841572, 9841573, 9841574, 9841575, 9841576, 9841577, 9841578, 9841579, 9841580, 9841581, 9841582, 9841583, 9841584, 9841585, 9841586, 9841587, 9841588, 9841589, 9841590, 9841591, 9841592, 9841593, 9841594, 9841595, 9841596, 9841597, 9841598, 9841599, 9841600, 9841601, 9841602, 9841603, 9841604, 9841605, 9841606, 9841607, 9841608, 9841609, 9841610, 9841611, 9841612, 9841613, 9841614, 9841615, 9841616, 9841617, 9841618, 9841619, 9841620, 9841621, 9841622, 9841623, 9841624, 9841625, 9841626, 9841627, 9841628, 9841629, 9841630, 9841631, 9841632, 9841633, 9841634, 9841635, 9841636, 9841637, 9841638, 9841639, 9841640, 9841641, 9841642, 9841643, 9841644, 9841645, 9841646, 9841647, 9841648, 9841649, 9841650, 9841651, 9841652, 9841653, 9841654, 9841655, 9841656, 9841657, 9841658, 9841659, 9841660, 9841661, 9841662, 9841663, 9841664, 9841665, 9841666, 9841667, 9841668, 9841669, 9841670, 9841671, 9841672, 9841673, 9841674, 9841675, 9841676, 9841677, 9841678, 9841679, 9841680, 9841681, 9841682, 9841683, 9841684, 9841685, 9841686, 9841687, 9841688, 9841689, 9841690, 9841691, 9841692, 9841693, 9841694, 9841695, 9841696, 9841697, 9841698, 9841699, 9841700, 9841701, 9841702, 9841703, 9841704, 9841705, 9841706, 9841707, 9841708, 9841709, 9841710, 9841711, 9841712, 9841713, 9841714, 9841715, 9841716, 9841717, 9841718, 9841719, 9841720, 9841721, 9841722, 9841723, 9841724, 9841725, 9841726, 9841727, 9841728, 9841729, 9841730, 9841731, 9841732, 9841733, 9841734, 9841735, 9841736, 9841737, 9841738, 9841739, 9841740, 9841741, 9841742, 9841743, 9841744, 9841745, 9841746, 9841747, 9841748, 9841749, 9841750, 9841751, 9841752, 9841753, 9841754, 9841755, 9841756, 9841757, 9841758, 9841759, 9841760, 9841761, 9841762, 9841763, 9841764, 9841765, 9841766, 9841767, 9841768, 9841769, 9841770, 9841771, 9841772, 9841773, 9841774, 9841775, 9841776, 9841777, 9841778, 9841779, 9841780, 9841781, 9841782, 9841783, 9841784, 9841785, 9841786, 9841787, 9841788, 9841789, 9841790, 9841791, 9841792, 9841793, 9841794, 9841795, 9841796, 9841797, 9841798, 9841799, 9841800, 9841801, 9841802, 9841803, 9841804, 9841805, 9841806, 9841807, 9841808, 9841809, 9841810, 9841811, 9841812, 9841813, 9841814, 9841815, 9841816, 9841817, 9841818, 9841819, 9841820, 9841821, 9841822, 9841823, 9841824, 9841825, 9841826, 9841827, 9841828, 9841829, 9841830, 9841831, 9841832, 9841833, 9841834, 9841835, 9841836, 9841837, 9841838, 9841839, 9841840, 9841841, 9841842, 9841843, 9841844, 9841845, 9841846, 9841847, 9841848, 9841849, 9841850, 9841851, 9841852, 9841853, 9841854, 9841855, 9841856, 9841857, 9841858, 9841859, 9841860, 9841861, 9841862, 9841863, 9841864, 9841865, 9841866, 9841867, 9841868, 9841869, 9841870, 9841871, 9841872, 9841873, 9841874, 9841875, 9841876, 9841877, 9841878, 9841879, 9841880, 9841881, 9841882, 9841883, 9841884, 9841885, 9841886, 9841887, 9841888, 9841889, 9841890, 9841891, 9841892, 9841893, 9841894, 9841895, 9841896, 9841897, 9841898, 9841899, 9841900, 9841901, 9841902, 9841903, 9841904, 9841905, 9841906, 9841907, 9841908, 9841909, 9841910, 9841911, 9841912, 9841913, 9841914, 9841915, 9841916, 9841917, 9841918, 9841919, 9841920, 9841921, 9841922, 9841923, 9841924, 9841925, 9841926, 9841927, 9841928, 9841929, 9841930, 9841931, 9841932, 9841933, 9841934, 9841935, 9841936, 9841937, 9841938, 9841939, 9841940, 9841941, 9841942, 9841943, 9841944, 9841945, 9841946, 9841947, 9841948, 9841949, 9841950, 9841951, 9841952, 9841953, 9841954, 9841955, 9841956, 9841957, 9841958, 9841959, 9841960, 9841961, 9841962, 9841963, 9841964, 9841965, 9841966, 9841967, 9841968, 9841969, 9841970, 9841971, 9841972, 9841973, 9841974, 9841975, 9841976, 9841977, 9841978, 9841979, 9841980, 9841981, 9841982, 9841983, 9841984, 9841985, 9841986, 9841987, 9841988, 9841989, 9841990, 9841991, 9841992, 9841993, 9841994, 9841995, 9841996, 9841997, 9841998, 9841999, 9842000, 9842001, 9842002, 9842003, 9842004, 9842005, 9842006, 9842007, 9842008, 9842009, 9842010, 9842011, 9842012, 9842013, 9842014, 9842015, 9842016, 9842017, 9842018, 9842019, 9842020, 9842021, 9842022, 9842023, 9842024, 9842025, 9842026, 9842027, 9842028, 9842029, 9842030, 9842031, 9842032, 9842033, 9842034, 9842035, 9842036, 9842037, 9842038, 9842039, 9842040, 9842041, 9842042, 9842043, 9842044, 9842045, 9842046, 9842047, 9842048, 9842049, 9842050, 9842051, 9842052, 9842053, 9842054, 9842055, 9842056, 9842057, 9842058, 9842059, 9842060, 9842061, 9842062, 9842063, 9842064, 9842065, 9842066, 9842067, 9842068, 9842069, 9842070, 9842071, 9842072, 9842073, 9842074, 9842075, 9842076, 9842077, 9842078, 9842079, 9842080, 9842081, 9842082, 9842083, 9842084, 9842085, 9842086, 9842087, 9842088, 9842089, 9842090, 9842091, 9842092, 9842093, 9842094, 9842095, 9842096, 9842097, 9842098, 9842099, 9842100, 9842101, 9842102, 9842103, 9842104, 9842105, 9842106, 9842107, 9842108, 9842109, 9842110, 9842111, 9842112, 9842113, 9842114, 9842115, 9842116, 9842117, 9842118, 9842119, 9842120, 9842121, 9842122, 9842123, 9842124, 9842125, 9842126, 9842127, 9842128, 9842129, 9842130, 9842131, 9842132, 9842133, 9842134, 9842135, 9842136, 9842137, 9842138, 9842139, 9842140, 9842141, 9842142, 9842143, 9842144, 9842145, 9842146, 9842147, 9842148, 9842149, 9842150, 9842151, 9842152, 9842153, 9842154, 9842155, 9842156, 9842157, 9842158, 9842159, 9842160, 9842161, 9842162, 9842163, 9842164, 9842165, 9842166, 9842167, 9842168, 9842169, 9842170, 9842171, 9842172, 9842173, 9842174, 9842175, 9842176, 9842177, 9842178, 9842179, 9842180, 9842181, 9842182, 9842183, 9842184, 9842185, 9842186, 9842187, 9842188, 9842189, 9842190, 9842191, 9842192, 9842193, 9842194, 9842195, 9842196, 9842197, 9842198, 9842199, 9842200, 9842201, 9842202, 9842203, 9842204, 9842205, 9842206, 9842207, 9842208, 9842209, 9842210, 9842211, 9842212, 9842213, 9842214, 9842215, 9842216, 9842217, 9842218, 9842219, 9842220, 9842221, 9842222, 9842223, 9842224, 9842225, 9842226, 9842227, 9842228, 9842229, 9842230, 9842231, 9842232, 9842233, 9842234, 9842235, 9842236, 9842237, 9842238, 9842239, 9842240, 9842241, 9842242, 9842243, 9842244, 9842245, 9842246, 9842247, 9842248, 9842249, 9842250, 9842251, 9842252, 9842253, 9842254, 9842255, 9842256, 9842257, 9842258, 9842259, 9842260, 9842261, 9842262, 9842263, 9842264, 9842265, 9842266, 9842267, 9842268, 9842269, 9842270, 9842271, 9842272, 9842273, 9842274, 9842275, 9842276, 9842277, 9842278, 9842279, 9842280, 9842281, 9842282, 9842283, 9842284, 9842285, 9842286, 9842287, 9842288, 9842289, 9842290, 9842291, 9842292, 9842293, 9842294, 9842295, 9842296, 9842297, 9842298, 9842299, 9842300, 9842301, 9842302, 9842303, 9842304, 9842305, 9842306, 9842307, 9842308, 9842309, 9842310, 9842311, 9842312, 9842313, 9842314, 9842315, 9842316, 9842317, 9842318, 9842319, 9842320, 9842321, 9842322, 9842323, 9842324, 9842325, 9842326, 9842327, 9842328, 9842329, 9842330, 9842331, 9842332, 9842333, 9842334, 9842335, 9842336, 9842337, 9842338, 9842339, 9842340, 9842341, 9842342, 9842343, 9842344, 9842345, 9842346, 9842347, 9842348, 9842349, 9842350, 9842351, 9842352, 9842353, 9842354, 9842355, 9842356, 9842357, 9842358, 9842359, 9842360, 9842361, 9842362, 9842363, 9842364, 9842365, 9842366, 9842367, 9842368, 9842369, 9842370, 9842371, 9842372, 9842373, 9842374, 9842375, 9842376, 9842377, 9842378, 9842379, 9842380, 9842381, 9842382, 9842383, 9842384, 9842385, 9842386, 9842387, 9842388, 9842389, 9842390, 9842391, 9842392, 9842393, 9842394, 9842395, 9842396, 9842397, 9842398, 9842399, 9842400, 9842401, 9842402, 9842403, 9842404, 9842405, 9842406, 9842407, 9842408, 9842409, 9842410, 9842411, 9842412, 9842413, 9842414, 9842415, 9842416, 9842417, 9842418, 9842419, 9842420, 9842421, 9842422, 9842423, 9842424, 9842425, 9842426, 9842427, 9842428, 9842429, 9842430, 9842431, 9842432, 9842433, 9842434, 9842435, 9842436, 9842437, 9842438, 9842439, 9842440, 9842441, 9842442, 9842443, 9842444, 9842445, 9842446, 9842447, 9842448, 9842449, 9842450, 9842451, 9842452, 9842453, 9842454, 9842455, 9842456, 9842457, 9842458, 9842459, 9842460, 9842461, 9842462, 9842463, 9842464, 9842465, 9842466, 9842467, 9842468, 9842469, 9842470, 9842471, 9842472, 9842473, 9842474, 9842475, 9842476, 9842477, 9842478, 9842479, 9842480, 9842481, 9842482, 9842483, 9842484, 9842485, 9842486, 9842487, 9842488, 9842489, 9842490, 9842491, 9842492, 9842493, 9842494, 9842495, 9842496, 9842497, 9842498, 9842499, 9842500, 9842501, 9842502, 9842503, 9842504, 9842505, 9842506, 9842507, 9842508, 9842509, 9842510, 9842511, 9842512, 9842513, 9842514, 9842515, 9842516, 9842517, 9842518, 9842519, 9842520, 9842521, 9842522, 9842523, 9842524, 9842525, 9842526, 9842527, 9842528, 9842529, 9842530, 9842531, 9842532, 9842533, 9842534, 9842535, 9842536, 9842537, 9842538, 9842539, 9842540, 9842541, 9842542, 9842543, 9842544, 9842545, 9842546, 9842547, 9842548, 9842549, 9842550, 9842551, 9842552, 9842553, 9842554, 9842555, 9842556, 9842557, 9842558, 9842559, 9842560, 9842561, 9842562, 9842563, 9842564, 9842565, 9842566, 9842567, 9842568, 9842569, 9842570, 9842571, 9842572, 9842573, 9842574, 9842575, 9842576, 9842577, 9842578, 9842579, 9842580, 9842581, 9842582, 9842583, 9842584, 9842585, 9842586, 9842587, 9842588, 9842589, 9842590, 9842591, 9842592, 9842593, 9842594, 9842595, 9842596, 9842597, 9842598, 9842599, 9842600, 9842601, 9842602, 9842603, 9842604, 9842605, 9842606, 9842607, 9842608, 9842609, 9842610, 9842611, 9842612, 9842613, 9842614, 9842615, 9842616, 9842617, 9842618, 9842619, 9842620, 9842621, 9842622, 9842623, 9842624, 9842625, 9842626, 9842627, 9842628, 9842629, 9842630, 9842631, 9842632, 9842633, 9842634, 9842635, 9842636, 9842637, 9842638, 9842639, 9842640, 9842641, 9842642, 9842643, 9842644, 9842645, 9842646, 9842647, 9842648, 9842649, 9842650, 9842651, 9842652, 9842653, 9842654, 9842655, 9842656, 9842657, 9842658, 9842659, 9842660, 9842661, 9842662, 9842663, 9842664, 9842665, 9842666, 9842667, 9842668, 9842669, 9842670, 9842671, 9842672, 9842673, 9842674, 9842675, 9842676, 9842677, 9842678, 9842679, 9842680, 9842681, 9842682, 9842683, 9842684, 9842685, 9842686, 9842687, 9842688, 9842689, 9842690, 9842691, 9842692, 9842693, 9842694, 9842695, 9842696, 9842697, 9842698, 9842699, 9842700, 9842701, 9842702, 9842703, 9842704, 9842705, 9842706, 9842707, 9842708, 9842709, 9842710, 9842711, 9842712, 9842713, 9842714, 9842715, 9842716, 9842717, 9842718, 9842719, 9842720, 9842721, 9842722, 9842723, 9842724, 9842725, 9842726, 9842727, 9842728, 9842729, 9842730, 9842731, 9842732, 9842733, 9842734, 9842735, 9842736, 9842737, 9842738, 9842739, 9842740, 9842741, 9842742, 9842743, 9842744, 9842745, 9842746, 9842747, 9842748, 9842749, 9842750, 9842751, 9842752, 9842753, 9842754, 9842755, 9842756, 9842757, 9842758, 9842759, 9842760, 9842761, 9842762, 9842763, 9842764, 9842765, 9842766, 9842767, 9842768, 9842769, 9842770, 9842771, 9842772, 9842773, 9842774, 9842775, 9842776, 9842777, 9842778, 9842779, 9842780, 9842781, 9842782, 9842783, 9842784, 9842785, 9842786, 9842787, 9842788, 9842789, 9842790, 9842791, 9842792, 9842793, 9842794, 9842795, 9842796, 9842797, 9842798, 9842799, 9842800, 9842801, 9842802, 9842803, 9842804, 9842805, 9842806, 9842807, 9842808, 9842809, 9842810, 9842811, 9842812, 9842813, 9842814, 9842815, 9842816, 9842817, 9842818, 9842819, 9842820, 9842821, 9842822, 9842823, 9842824, 9842825, 9842826, 9842827, 9842828, 9842829, 9842830, 9842831, 9842832, 9842833, 9842834, 9842835, 9842836, 9842837, 9842838, 9842839, 9842840, 9842841, 9842842, 9842843, 9842844, 9842845, 9842846, 9842847, 9842848, 9842849, 9842850, 9842851, 9842852, 9842853, 9842854, 9842855, 9842856, 9842857, 9842858, 9842859, 9842860, 9842861, 9842862, 9842863, 9842864, 9842865, 9842866, 9842867, 9842868, 9842869, 9842870, 9842871, 9842872, 9842873, 9842874, 9842875, 9842876, 9842877, 9842878, 9842879, 9842880, 9842881, 9842882, 9842883, 9842884, 9842885, 9842886, 9842887, 9842888, 9842889, 9842890, 9842891, 9842892, 9842893, 9842894, 9842895, 9842896, 9842897, 9842898, 9842899, 9842900, 9842901, 9842902, 9842903, 9842904, 9842905, 9842906, 9842907, 9842908, 9842909, 9842910, 9842911, 9842912, 9842913, 9842914, 9842915, 9842916, 9842917, 9842918, 9842919, 9842920, 9842921, 9842922, 9842923, 9842924, 9842925, 9842926, 9842927, 9842928, 9842929, 9842930, 9842931, 9842932, 9842933, 9842934, 9842935, 9842936, 9842937, 9842938, 9842939, 9842940, 9842941, 9842942, 9842943, 9842944, 9842945, 9842946, 9842947, 9842948, 9842949, 9842950, 9842951, 9842952, 9842953, 9842954, 9842955, 9842956, 9842957, 9842958, 9842959, 9842960, 9842961, 9842962, 9842963, 9842964, 9842965, 9842966, 9842967, 9842968, 9842969, 9842970, 9842971, 9842972, 9842973, 9842974, 9842975, 9842976, 9842977, 9842978, 9842979, 9842980, 9842981, 9842982, 9842983, 9842984, 9842985, 9842986, 9842987, 9842988, 9842989, 9842990, 9842991, 9842992, 9842993, 9842994, 9842995, 9842996, 9842997, 9842998, 9842999, 9843000, 9843001, 9843002, 9843003, 9843004, 9843005, 9843006, 9843007, 9843008, 9843009, 9843010, 9843011, 9843012, 9843013, 9843014, 9843015, 9843016, 9843017, 9843018, 9843019, 9843020, 9843021, 9843022, 9843023, 9843024, 9843025, 9843026, 9843027, 9843028, 9843029, 9843030, 9843031, 9843032, 9843033, 9843034, 9843035, 9843036, 9843037, 9843038, 9843039, 9843040, 9843041, 9843042, 9843043, 9843044, 9843045, 9843046, 9843047, 9843048, 9843049, 9843050, 9843051, 9843052, 9843053, 9843054, 9843055, 9843056, 9843057, 9843058, 9843059, 9843060, 9843061, 9843062, 9843063, 9843064, 9843065, 9843066, 9843067, 9843068, 9843069, 9843070, 9843071, 9843072, 9843073, 9843074, 9843075, 9843076, 9843077, 9843078, 9843079, 9843080, 9843081, 9843082, 9843083, 9843084, 9843085, 9843086, 9843087, 9843088, 9843089, 9843090, 9843091, 9843092, 9843093, 9843094, 9843095, 9843096, 9843097, 9843098, 9843099, 9843100, 9843101, 9843102, 9843103, 9843104, 9843105, 9843106, 9843107, 9843108, 9843109, 9843110, 9843111, 9843112, 9843113, 9843114, 9843115, 9843116, 9843117, 9843118, 9843119, 9843120, 9843121, 9843122, 9843123, 9843124, 9843125, 9843126, 9843127, 9843128, 9843129, 9843130, 9843131, 9843132, 9843133, 9843134, 9843135, 9843136, 9843137, 9843138, 9843139, 9843140, 9843141, 9843142, 9843143, 9843144, 9843145, 9843146, 9843147, 9843148, 9843149, 9843150, 9843151, 9843152, 9843153, 9843154, 9843155, 9843156, 9843157, 9843158, 9843159, 9843160, 9843161, 9843162, 9843163, 9843164, 9843165, 9843166, 9843167, 9843168, 9843169, 9843170, 9843171, 9843172, 9843173, 9843174, 9843175, 9843176, 9843177, 9843178, 9843179, 9843180, 9843181, 9843182, 9843183, 9843184, 9843185, 9843186, 9843187, 9843188, 9843189, 9843190, 9843191, 9843192, 9843193, 9843194, 9843195, 9843196, 9843197, 9843198, 9843199, 9843200, 9843201, 9843202, 9843203, 9843204, 9843205, 9843206, 9843207, 9843208, 9843209, 9843210, 9843211, 9843212, 9843213, 9843214, 9843215, 9843216, 9843217, 9843218, 9843219, 9843220, 9843221, 9843222, 9843223, 9843224, 9843225, 9843226, 9843227, 9843228, 9843229, 9843230, 9843231, 9843232, 9843233, 9843234, 9843235, 9843236, 9843237, 9843238, 9843239, 9843240, 9843241, 9843242, 9843243, 9843244, 9843245, 9843246, 9843247, 9843248, 9843249, 9843250, 9843251, 9843252, 9843253, 9843254, 9843255, 9843256, 9843257, 9843258, 9843259, 9843260, 9843261, 9843262, 9843263, 9843264, 9843265, 9843266, 9843267, 9843268, 9843269, 9843270, 9843271, 9843272, 9843273, 9843274, 9843275, 9843276, 9843277, 9843278, 9843279, 9843280, 9843281, 9843282, 9843283, 9843284, 9843285, 9843286, 9843287, 9843288, 9843289, 9843290, 9843291, 9843292, 9843293, 9843294, 9843295, 9843296, 9843297, 9843298, 9843299, 9843300, 9843301, 9843302, 9843303, 9843304, 9843305, 9843306, 9843307, 9843308, 9843309, 9843310, 9843311, 9843312, 9843313, 9843314, 9843315, 9843316, 9843317, 9843318, 9843319, 9843320, 9843321, 9843322, 9843323, 9843324, 9843325, 9843326, 9843327, 9843328, 9843329, 9843330, 9843331, 9843332, 9843333, 9843334, 9843335, 9843336, 9843337, 9843338, 9843339, 9843340, 9843341, 9843342, 9843343, 9843344, 9843345, 9843346, 9843347, 9843348, 9843349, 9843350, 9843351, 9843352, 9843353, 9843354, 9843355, 9843356, 9843357, 9843358, 9843359, 9843360, 9843361, 9843362, 9843363, 9843364, 9843365, 9843366, 9843367, 9843368, 9843369, 9843370, 9843371, 9843372, 9843373, 9843374, 9843375, 9843376, 9843377, 9843378, 9843379, 9843380, 9843381, 9843382, 9843383, 9843384, 9843385, 9843386, 9843387, 9843388, 9843389, 9843390, 9843391, 9843392, 9843393, 9843394, 9843395, 9843396, 9843397, 9843398, 9843399, 9843400, 9843401, 9843402, 9843403, 9843404, 9843405, 9843406, 9843407, 9843408, 9843409, 9843410, 9843411, 9843412, 9843413, 9843414, 9843415, 9843416, 9843417, 9843418, 9843419, 9843420, 9843421, 9843422, 9843423, 9843424, 9843425, 9843426, 9843427, 9843428, 9843429, 9843430, 9843431, 9843432, 9843433, 9843434, 9843435, 9843436, 9843437, 9843438, 9843439, 9843440, 9843441, 9843442, 9843443, 9843444, 9843445, 9843446, 9843447, 9843448, 9843449, 9843450, 9843451, 9843452, 9843453, 9843454, 9843455, 9843456, 9843457, 9843458, 9843459, 9843460, 9843461, 9843462, 9843463, 9843464, 9843465, 9843466, 9843467, 9843468, 9843469, 9843470, 9843471, 9843472, 9843473, 9843474, 9843475, 9843476, 9843477, 9843478, 9843479, 9843480, 9843481, 9843482, 9843483, 9843484, 9843485, 9843486, 9843487, 9843488, 9843489, 9843490, 9843491, 9843492, 9843493, 9843494, 9843495, 9843496, 9843497, 9843498, 9843499, 9843500, 9843501, 9843502, 9843503, 9843504, 9843505, 9843506, 9843507, 9843508, 9843509, 9843510, 9843511, 9843512, 9843513, 9843514, 9843515, 9843516, 9843517, 9843518, 9843519, 9843520, 9843521, 9843522, 9843523, 9843524, 9843525, 9843526, 9843527, 9843528, 9843529, 9843530, 9843531, 9843532, 9843533, 9843534, 9843535, 9843536, 9843537, 9843538, 9843539, 9843540, 9843541, 9843542, 9843543, 9843544, 9843545, 9843546, 9843547, 9843548, 9843549, 9843550, 9843551, 9843552, 9843553, 9843554, 9843555, 9843556, 9843557, 9843558, 9843559, 9843560, 9843561, 9843562, 9843563, 9843564, 9843565, 9843566, 9843567, 9843568, 9843569, 9843570, 9843571, 9843572, 9843573, 9843574, 9843575, 9843576, 9843577, 9843578, 9843579, 9843580, 9843581, 9843582, 9843583, 9843584, 9843585, 9843586, 9843587, 9843588, 9843589, 9843590, 9843591, 9843592, 9843593, 9843594, 9843595, 9843596, 9843597, 9843598, 9843599, 9843600, 9843601, 9843602, 9843603, 9843604, 9843605, 9843606, 9843607, 9843608, 9843609, 9843610, 9843611, 9843612, 9843613, 9843614, 9843615, 9843616, 9843617, 9843618, 9843619, 9843620, 9843621, 9843622, 9843623, 9843624, 9843625, 9843626, 9843627, 9843628, 9843629, 9843630, 9843631, 9843632, 9843633, 9843634, 9843635, 9843636, 9843637, 9843638, 9843639, 9843640, 9843641, 9843642, 9843643, 9843644, 9843645, 9843646, 9843647, 9843648, 9843649, 9843650, 9843651, 9843652, 9843653, 9843654, 9843655, 9843656, 9843657, 9843658, 9843659, 9843660, 9843661, 9843662, 9843663, 9843664, 9843665, 9843666, 9843667, 9843668, 9843669, 9843670, 9843671, 9843672, 9843673, 9843674, 9843675, 9843676, 9843677, 9843678, 9843679, 9843680, 9843681, 9843682, 9843683, 9843684, 9843685, 9843686, 9843687, 9843688, 9843689, 9843690, 9843691, 9843692, 9843693, 9843694, 9843695, 9843696, 9843697, 9843698, 9843699, 9843700, 9843701, 9843702, 9843703, 9843704, 9843705, 9843706, 9843707, 9843708, 9843709, 9843710, 9843711, 9843712, 9843713, 9843714, 9843715, 9843716, 9843717, 9843718, 9843719, 9843720, 9843721, 9843722, 9843723, 9843724, 9843725, 9843726, 9843727, 9843728, 9843729, 9843730, 9843731, 9843732, 9843733, 9843734, 9843735, 9843736, 9843737, 9843738, 9843739, 9843740, 9843741, 9843742, 9843743, 9843744, 9843745, 9843746, 9843747, 9843748, 9843749, 9843750, 9843751, 9843752, 9843753, 9843754, 9843755, 9843756, 9843757, 9843758, 9843759, 9843760, 9843761, 9843762, 9843763, 9843764, 9843765, 9843766, 9843767, 9843768, 9843769, 9843770, 9843771, 9843772, 9843773, 9843774, 9843775, 9843776, 9843777, 9843778, 9843779, 9843780, 9843781, 9843782, 9843783, 9843784, 9843785, 9843786, 9843787, 9843788, 9843789, 9843790, 9843791, 9843792, 9843793, 9843794, 9843795, 9843796, 9843797, 9843798, 9843799, 9843800, 9843801, 9843802, 9843803, 9843804, 9843805, 9843806, 9843807, 9843808, 9843809, 9843810, 9843811, 9843812, 9843813, 9843814, 9843815, 9843816, 9843817, 9843818, 9843819, 9843820, 9843821, 9843822, 9843823, 9843824, 9843825, 9843826, 9843827, 9843828, 9843829, 9843830, 9843831, 9843832, 9843833, 9843834, 9843835, 9843836, 9843837, 9843838, 9843839, 9843840, 9843841, 9843842, 9843843, 9843844, 9843845, 9843846, 9843847, 9843848, 9843849, 9843850, 9843851, 9843852, 9843853, 9843854, 9843855, 9843856, 9843857, 9843858, 9843859, 9843860, 9843861, 9843862, 9843863, 9843864, 9843865, 9843866, 9843867, 9843868, 9843869, 9843870, 9843871, 9843872, 9843873, 9843874, 9843875, 9843876, 9843877, 9843878, 9843879, 9843880, 9843881, 9843882, 9843883, 9843884, 9843885, 9843886, 9843887, 9843888, 9843889, 9843890, 9843891, 9843892, 9843893, 9843894, 9843895, 9843896, 9843897, 9843898, 9843899, 9843900, 9843901, 9843902, 9843903, 9843904, 9843905, 9843906, 9843907, 9843908, 9843909, 9843910, 9843911, 9843912, 9843913, 9843914, 9843915, 9843916, 9843917, 9843918, 9843919, 9843920, 9843921, 9843922, 9843923, 9843924, 9843925, 9843926, 9843927, 9843928, 9843929, 9843930, 9843931, 9843932, 9843933, 9843934, 9843935, 9843936, 9843937, 9843938, 9843939, 9843940, 9843941, 9843942, 9843943, 9843944, 9843945, 9843946, 9843947, 9843948, 9843949, 9843950, 9843951, 9843952, 9843953, 9843954, 9843955, 9843956, 9843957, 9843958, 9843959, 9843960, 9843961, 9843962, 9843963, 9843964, 9843965, 9843966, 9843967, 9843968, 9843969, 9843970, 9843971, 9843972, 9843973, 9843974, 9843975, 9843976, 9843977, 9843978, 9843979, 9843980, 9843981, 9843982, 9843983, 9843984, 9843985, 9843986, 9843987, 9843988, 9843989, 9843990, 9843991, 9843992, 9843993, 9843994, 9843995, 9843996, 9843997, 9843998, 9843999, 9844000, 9844001, 9844002, 9844003, 9844004, 9844005, 9844006, 9844007, 9844008, 9844009, 9844010, 9844011, 9844012, 9844013, 9844014, 9844015, 9844016, 9844017, 9844018, 9844019, 9844020, 9844021, 9844022, 9844023, 9844024, 9844025, 9844026, 9844027, 9844028, 9844029, 9844030, 9844031, 9844032, 9844033, 9844034, 9844035, 9844036, 9844037, 9844038, 9844039, 9844040, 9844041, 9844042, 9844043, 9844044, 9844045, 9844046, 9844047, 9844048, 9844049, 9844050, 9844051, 9844052, 9844053, 9844054, 9844055, 9844056, 9844057, 9844058, 9844059, 9844060, 9844061, 9844062, 9844063, 9844064, 9844065, 9844066, 9844067, 9844068, 9844069, 9844070, 9844071, 9844072, 9844073, 9844074, 9844075, 9844076, 9844077, 9844078, 9844079, 9844080, 9844081, 9844082, 9844083, 9844084, 9844085, 9844086, 9844087, 9844088, 9844089, 9844090, 9844091, 9844092, 9844093, 9844094, 9844095, 9844096, 9844097, 9844098, 9844099, 9844100, 9844101, 9844102, 9844103, 9844104, 9844105, 9844106, 9844107, 9844108, 9844109, 9844110, 9844111, 9844112, 9844113, 9844114, 9844115, 9844116, 9844117, 9844118, 9844119, 9844120, 9844121, 9844122, 9844123, 9844124, 9844125, 9844126, 9844127, 9844128, 9844129, 9844130, 9844131, 9844132, 9844133, 9844134, 9844135, 9844136, 9844137, 9844138, 9844139, 9844140, 9844141, 9844142, 9844143, 9844144, 9844145, 9844146, 9844147, 9844148, 9844149, 9844150, 9844151, 9844152, 9844153, 9844154, 9844155, 9844156, 9844157, 9844158, 9844159, 9844160, 9844161, 9844162, 9844163, 9844164, 9844165, 9844166, 9844167, 9844168, 9844169, 9844170, 9844171, 9844172, 9844173, 9844174, 9844175, 9844176, 9844177, 9844178, 9844179, 9844180, 9844181, 9844182, 9844183, 9844184, 9844185, 9844186, 9844187, 9844188, 9844189, 9844190, 9844191, 9844192, 9844193, 9844194, 9844195, 9844196, 9844197, 9844198, 9844199, 9844200, 9844201, 9844202, 9844203, 9844204, 9844205, 9844206, 9844207, 9844208, 9844209, 9844210, 9844211, 9844212, 9844213, 9844214, 9844215, 9844216, 9844217, 9844218, 9844219, 9844220, 9844221, 9844222, 9844223, 9844224, 9844225, 9844226, 9844227, 9844228, 9844229, 9844230, 9844231, 9844232, 9844233, 9844234, 9844235, 9844236, 9844237, 9844238, 9844239, 9844240, 9844241, 9844242, 9844243, 9844244, 9844245, 9844246, 9844247, 9844248, 9844249, 9844250, 9844251, 9844252, 9844253, 9844254, 9844255, 9844256, 9844257, 9844258, 9844259, 9844260, 9844261, 9844262, 9844263, 9844264, 9844265, 9844266, 9844267, 9844268, 9844269, 9844270, 9844271, 9844272, 9844273, 9844274, 9844275, 9844276, 9844277, 9844278, 9844279, 9844280, 9844281, 9844282, 9844283, 9844284, 9844285, 9844286, 9844287, 9844288, 9844289, 9844290, 9844291, 9844292, 9844293, 9844294, 9844295, 9844296, 9844297, 9844298, 9844299, 9844300, 9844301, 9844302, 9844303, 9844304, 9844305, 9844306, 9844307, 9844308, 9844309, 9844310, 9844311, 9844312, 9844313, 9844314, 9844315, 9844316, 9844317, 9844318, 9844319, 9844320, 9844321, 9844322, 9844323, 9844324, 9844325, 9844326, 9844327, 9844328, 9844329, 9844330, 9844331, 9844332, 9844333, 9844334, 9844335, 9844336, 9844337, 9844338, 9844339, 9844340, 9844341, 9844342, 9844343, 9844344, 9844345, 9844346, 9844347, 9844348, 9844349, 9844350, 9844351, 9844352, 9844353, 9844354, 9844355, 9844356, 9844357, 9844358, 9844359, 9844360, 9844361, 9844362, 9844363, 9844364, 9844365, 9844366, 9844367, 9844368, 9844369, 9844370, 9844371, 9844372, 9844373, 9844374, 9844375, 9844376, 9844377, 9844378, 9844379, 9844380, 9844381, 9844382, 9844383, 9844384, 9844385, 9844386, 9844387, 9844388, 9844389, 9844390, 9844391, 9844392, 9844393, 9844394, 9844395, 9844396, 9844397, 9844398, 9844399, 9844400, 9844401, 9844402, 9844403, 9844404, 9844405, 9844406, 9844407, 9844408, 9844409, 9844410, 9844411, 9844412, 9844413, 9844414, 9844415, 9844416, 9844417, 9844418, 9844419, 9844420, 9844421, 9844422, 9844423, 9844424, 9844425, 9844426, 9844427, 9844428, 9844429, 9844430, 9844431, 9844432, 9844433, 9844434, 9844435, 9844436, 9844437, 9844438, 9844439, 9844440, 9844441, 9844442, 9844443, 9844444, 9844445, 9844446, 9844447, 9844448, 9844449, 9844450, 9844451, 9844452, 9844453, 9844454, 9844455, 9844456, 9844457, 9844458, 9844459, 9844460, 9844461, 9844462, 9844463, 9844464, 9844465, 9844466, 9844467, 9844468, 9844469, 9844470, 9844471, 9844472, 9844473, 9844474, 9844475, 9844476, 9844477, 9844478, 9844479, 9844480, 9844481, 9844482, 9844483, 9844484, 9844485, 9844486, 9844487, 9844488, 9844489, 9844490, 9844491, 9844492, 9844493, 9844494, 9844495, 9844496, 9844497, 9844498, 9844499, 9844500, 9844501, 9844502, 9844503, 9844504, 9844505, 9844506, 9844507, 9844508, 9844509, 9844510, 9844511, 9844512, 9844513, 9844514, 9844515, 9844516, 9844517, 9844518, 9844519, 9844520, 9844521, 9844522, 9844523, 9844524, 9844525, 9844526, 9844527, 9844528, 9844529, 9844530, 9844531, 9844532, 9844533, 9844534, 9844535, 9844536, 9844537, 9844538, 9844539, 9844540, 9844541, 9844542, 9844543, 9844544, 9844545, 9844546, 9844547, 9844548, 9844549, 9844550, 9844551, 9844552, 9844553, 9844554, 9844555, 9844556, 9844557, 9844558, 9844559, 9844560, 9844561, 9844562, 9844563, 9844564, 9844565, 9844566, 9844567, 9844568, 9844569, 9844570, 9844571, 9844572, 9844573, 9844574, 9844575, 9844576, 9844577, 9844578, 9844579, 9844580, 9844581, 9844582, 9844583, 9844584, 9844585, 9844586, 9844587, 9844588, 9844589, 9844590, 9844591, 9844592, 9844593, 9844594, 9844595, 9844596, 9844597, 9844598, 9844599, 9844600, 9844601, 9844602, 9844603, 9844604, 9844605, 9844606, 9844607, 9844608, 9844609, 9844610, 9844611, 9844612, 9844613, 9844614, 9844615, 9844616, 9844617, 9844618, 9844619, 9844620, 9844621, 9844622, 9844623, 9844624, 9844625, 9844626, 9844627, 9844628, 9844629, 9844630, 9844631, 9844632, 9844633, 9844634, 9844635, 9844636, 9844637, 9844638, 9844639, 9844640, 9844641, 9844642, 9844643, 9844644, 9844645, 9844646, 9844647, 9844648, 9844649, 9844650, 9844651, 9844652, 9844653, 9844654, 9844655, 9844656, 9844657, 9844658, 9844659, 9844660, 9844661, 9844662, 9844663, 9844664, 9844665, 9844666, 9844667, 9844668, 9844669, 9844670, 9844671, 9844672, 9844673, 9844674, 9844675, 9844676, 9844677, 9844678, 9844679, 9844680, 9844681, 9844682, 9844683, 9844684, 9844685, 9844686, 9844687, 9844688, 9844689, 9844690, 9844691, 9844692, 9844693, 9844694, 9844695, 9844696, 9844697, 9844698, 9844699, 9844700, 9844701, 9844702, 9844703, 9844704, 9844705, 9844706, 9844707, 9844708, 9844709, 9844710, 9844711, 9844712, 9844713, 9844714, 9844715, 9844716, 9844717, 9844718, 9844719, 9844720, 9844721, 9844722, 9844723, 9844724, 9844725, 9844726, 9844727, 9844728, 9844729, 9844730, 9844731, 9844732, 9844733, 9844734, 9844735, 9844736, 9844737, 9844738, 9844739, 9844740, 9844741, 9844742, 9844743, 9844744, 9844745, 9844746, 9844747, 9844748, 9844749, 9844750, 9844751, 9844752, 9844753, 9844754, 9844755, 9844756, 9844757, 9844758, 9844759, 9844760, 9844761, 9844762, 9844763, 9844764, 9844765, 9844766, 9844767, 9844768, 9844769, 9844770, 9844771, 9844772, 9844773, 9844774, 9844775, 9844776, 9844777, 9844778, 9844779, 9844780, 9844781, 9844782, 9844783, 9844784, 9844785, 9844786, 9844787, 9844788, 9844789, 9844790, 9844791, 9844792, 9844793, 9844794, 9844795, 9844796, 9844797, 9844798, 9844799, 9844800, 9844801, 9844802, 9844803, 9844804, 9844805, 9844806, 9844807, 9844808, 9844809, 9844810, 9844811, 9844812, 9844813, 9844814, 9844815, 9844816, 9844817, 9844818, 9844819, 9844820, 9844821, 9844822, 9844823, 9844824, 9844825, 9844826, 9844827, 9844828, 9844829, 9844830, 9844831, 9844832, 9844833, 9844834, 9844835, 9844836, 9844837, 9844838, 9844839, 9844840, 9844841, 9844842, 9844843, 9844844, 9844845, 9844846, 9844847, 9844848, 9844849, 9844850, 9844851, 9844852, 9844853, 9844854, 9844855, 9844856, 9844857, 9844858, 9844859, 9844860, 9844861, 9844862, 9844863, 9844864, 9844865, 9844866, 9844867, 9844868, 9844869, 9844870, 9844871, 9844872, 9844873, 9844874, 9844875, 9844876, 9844877, 9844878, 9844879, 9844880, 9844881, 9844882, 9844883, 9844884, 9844885, 9844886, 9844887, 9844888, 9844889, 9844890, 9844891, 9844892, 9844893, 9844894, 9844895, 9844896, 9844897, 9844898, 9844899, 9844900, 9844901, 9844902, 9844903, 9844904, 9844905, 9844906, 9844907, 9844908, 9844909, 9844910, 9844911, 9844912, 9844913, 9844914, 9844915, 9844916, 9844917, 9844918, 9844919, 9844920, 9844921, 9844922, 9844923, 9844924, 9844925, 9844926, 9844927, 9844928, 9844929, 9844930, 9844931, 9844932, 9844933, 9844934, 9844935, 9844936, 9844937, 9844938, 9844939, 9844940, 9844941, 9844942, 9844943, 9844944, 9844945, 9844946, 9844947, 9844948, 9844949, 9844950, 9844951, 9844952, 9844953, 9844954, 9844955, 9844956, 9844957, 9844958, 9844959, 9844960, 9844961, 9844962, 9844963, 9844964, 9844965, 9844966, 9844967, 9844968, 9844969, 9844970, 9844971, 9844972, 9844973, 9844974, 9844975, 9844976, 9844977, 9844978, 9844979, 9844980, 9844981, 9844982, 9844983, 9844984, 9844985, 9844986, 9844987, 9844988, 9844989, 9844990, 9844991, 9844992, 9844993, 9844994, 9844995, 9844996, 9844997, 9844998, 9844999] |
| 完整逐局来源 | source-ledger.json |
| 冻结源码SHA | {'scripts/prism_cloud_storage_snapshot.py': 'b417e62c6aa2ce56ad2968ab0ac4c952b4a954514128a6923efc272129f5eb8c', 'scripts/prism_dsw_arena.py': '172b6f9edbb69b2d0fc139cd3ac4678d5f0392f97b59ebd09164467beda7b399', 'scripts/prism_match_details.py': '0f7fb79de0a65e60dfcb914716c99562fa44dd7673e6c1c0ea5ee4916ba11bc4', 'scripts/prism_notebook_arena.py': '84baf17c3e9fb31638bb5e56799ceffaec41b96a7a358b289023ab55a6f7b935', 'scripts/prism_notebook_report.py': 'bc7dd35146d795c28c8f8a7fb3910cfe3b832e88884de32b93a0d010ff6fd9ec', 'scripts/prism_ppo_fixed_eval.py': 'fb6683d0f0d91d92efafef1d136545b3dabf376e014e066b19beb43fe78aeacb'} |




## M67种子A最终c20未发布训练检查点 对阵 Prism Alpha v0.1.5



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 10000/5000 | 6005/88/3907 | 60.0500% | 60.4900% | 59.1100% / 61.0000% | 59.5500% / 61.4250% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 5000 | 3106/55/1839 | 62.1200 | 62.6700 | 14.5610 | 13.5736 |
| P1（后手） | 5000 | 2899/33/2068 | 57.9800 | 58.3100 | 14.5208 | 13.5784 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.5409 | 13.5760 |
| VP/本人全部决策 | 0.5301 | 0.4949 |
| VP/本人Main | 0.5302 | 0.4950 |
| VP/全局ply | 0.2651 | 0.2475 |
| 永久折扣/购卡每局 | 11.2827 | 11.8003 |
| 贵族/局 | 0.3690 | 0.4559 |
| 获得贵族的对局% | 32.1000 | 37.3400 |
| 预留获取/局 | 3.6470 | 3.2700 |
| 预留买回/局 | 1.5579 | 1.2549 |
| 终局未买回预留/局 | 2.0891 | 2.0151 |
| 预留买回/获取%（总分母） | 42.7173 | 38.3761 |
| 购入0 VP卡/局 | 5.5018 | 6.1062 |
| 购入1 VP卡/局 | 1.9143 | 2.1225 |
| 购入2 VP卡/局 | 1.7908 | 1.8176 |
| 购入3 VP卡/局 | 0.8000 | 0.8336 |
| 购入4 VP卡/局 | 0.8410 | 0.6522 |
| 购入5 VP卡/局 | 0.4348 | 0.2682 |
| White折扣/局 | 2.4266 | 2.3448 |
| Blue折扣/局 | 2.0141 | 2.3510 |
| Green折扣/局 | 2.1109 | 2.4345 |
| Red折扣/局 | 2.4273 | 2.2356 |
| Black折扣/局 | 2.3038 | 2.4344 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 97248 / 35.4550% | 105454 / 38.4448% |
| buy_reserved | 15579 / 5.6798% | 12549 / 4.5749% |
| take_tokens | 124949 / 45.5543% | 123542 / 45.0390% |
| reserve_market | 36464 / 13.2942% | 32698 / 11.9205% |
| reserve_deck | 6 / 0.0022% | 2 / 0.0007% |
| choose_noble | 38 / 0.0139% | 52 / 0.0190% |
| pass | 2 / 0.0007% | 3 / 0.0011% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 548586 / 54.8586 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 27.4337 / 20.0000 / 27.0000 / 3237.0000 / 40.1612 |
| Main轮均值 | 27.4248 |
| 绝对终局分差 | 3.6517 |
| 分差≤2对局% | 35.3200 |
| 对局监督墙钟秒：累计 / 均 / P95 | 4950.3575 / 0.4950 / 0.7183 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/a/cycle-20-export/weights.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/a/cycle-20-export/weights.json', 'sha256': 'db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', 'sha256': '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |



# b-direct 原始完整报告

# Prism 通用对战结果（DSW / SSH）



**产物：已完成全部固定网格，Rust规则回放验核与双方指标守恒通过。**



**竞技：DEVELOPMENT_ONLY_NOT_PROMOTED。**这是独立通用开发测量，没有执行任何里程碑正式晋级门。



**风格：描述性数据。**不凭单一更高/更低经济指标授予风格身份。



候选按用户声明的完整模型名及导出SHA识别，未发布检查点仍须在名称中明确标注。每对手恰好双座种子块；个人表按模型身份归并，物理P0不总是候选。



## 候选匹配比较



只有一个候选，匹配基线到候选比较NOT_APPLICABLE。

↑/↓仅为方向标记，不表示更好或差异显著。下面CI为逐对手描述性双座bootstrap；不做多门验收或发布。若只有一个种子块，CI退化，不能据此确认稳定性。



## 总体执行与来源



| 字段 | 记录 |
| --- | --- |
| 固定局数 | 10000 |
| 并发进程 / 每进程库线程 | 4 / 1 |
| 累计已测活动墙钟秒（至报告前监测点） | 2329.4754 |
| 首次派发至报告生成秒（包含暂停） | 2370.2998 |
| 时钟范围 | standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download |
| 资源监控 | observed process-tree soft limits; shared platform cgroups are not owned |
| 已测负载 | {'observed_processes': 2, 'peak_observed_rss_bytes': 236310528, 'process_tree_cpu_seconds': 6490.669999999999, 'process_tree_rss_sum_bytes': 38006784, 'scope': 'sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages'} |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |
| 配置SHA256 | 3f124956a6ead97f966d184a8d3ccf078d082e4542d0853814f2a10ee8d7ac2f |
| plan SHA256 | 5a94e91185a9d3fbbcee2c861fe4d6977b50be85b61ce6ce18690a741a004eb4 |
| engine SHA256 | 6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f |
| metrics SHA256 | 39c630d5e0a9e0611ca4ec8c8b2e4a78817bf971c7bdc7446b614035aedbcb37 |
| Git基线 / 源码dirty | NOT_AVAILABLE / None |
| Bootstrap | {'kind': 'descriptive paired seed blocks, not acceptance', 'samples': 20000, 'seed': 64049999} |
| 种子 | [9840000, 9840001, 9840002, 9840003, 9840004, 9840005, 9840006, 9840007, 9840008, 9840009, 9840010, 9840011, 9840012, 9840013, 9840014, 9840015, 9840016, 9840017, 9840018, 9840019, 9840020, 9840021, 9840022, 9840023, 9840024, 9840025, 9840026, 9840027, 9840028, 9840029, 9840030, 9840031, 9840032, 9840033, 9840034, 9840035, 9840036, 9840037, 9840038, 9840039, 9840040, 9840041, 9840042, 9840043, 9840044, 9840045, 9840046, 9840047, 9840048, 9840049, 9840050, 9840051, 9840052, 9840053, 9840054, 9840055, 9840056, 9840057, 9840058, 9840059, 9840060, 9840061, 9840062, 9840063, 9840064, 9840065, 9840066, 9840067, 9840068, 9840069, 9840070, 9840071, 9840072, 9840073, 9840074, 9840075, 9840076, 9840077, 9840078, 9840079, 9840080, 9840081, 9840082, 9840083, 9840084, 9840085, 9840086, 9840087, 9840088, 9840089, 9840090, 9840091, 9840092, 9840093, 9840094, 9840095, 9840096, 9840097, 9840098, 9840099, 9840100, 9840101, 9840102, 9840103, 9840104, 9840105, 9840106, 9840107, 9840108, 9840109, 9840110, 9840111, 9840112, 9840113, 9840114, 9840115, 9840116, 9840117, 9840118, 9840119, 9840120, 9840121, 9840122, 9840123, 9840124, 9840125, 9840126, 9840127, 9840128, 9840129, 9840130, 9840131, 9840132, 9840133, 9840134, 9840135, 9840136, 9840137, 9840138, 9840139, 9840140, 9840141, 9840142, 9840143, 9840144, 9840145, 9840146, 9840147, 9840148, 9840149, 9840150, 9840151, 9840152, 9840153, 9840154, 9840155, 9840156, 9840157, 9840158, 9840159, 9840160, 9840161, 9840162, 9840163, 9840164, 9840165, 9840166, 9840167, 9840168, 9840169, 9840170, 9840171, 9840172, 9840173, 9840174, 9840175, 9840176, 9840177, 9840178, 9840179, 9840180, 9840181, 9840182, 9840183, 9840184, 9840185, 9840186, 9840187, 9840188, 9840189, 9840190, 9840191, 9840192, 9840193, 9840194, 9840195, 9840196, 9840197, 9840198, 9840199, 9840200, 9840201, 9840202, 9840203, 9840204, 9840205, 9840206, 9840207, 9840208, 9840209, 9840210, 9840211, 9840212, 9840213, 9840214, 9840215, 9840216, 9840217, 9840218, 9840219, 9840220, 9840221, 9840222, 9840223, 9840224, 9840225, 9840226, 9840227, 9840228, 9840229, 9840230, 9840231, 9840232, 9840233, 9840234, 9840235, 9840236, 9840237, 9840238, 9840239, 9840240, 9840241, 9840242, 9840243, 9840244, 9840245, 9840246, 9840247, 9840248, 9840249, 9840250, 9840251, 9840252, 9840253, 9840254, 9840255, 9840256, 9840257, 9840258, 9840259, 9840260, 9840261, 9840262, 9840263, 9840264, 9840265, 9840266, 9840267, 9840268, 9840269, 9840270, 9840271, 9840272, 9840273, 9840274, 9840275, 9840276, 9840277, 9840278, 9840279, 9840280, 9840281, 9840282, 9840283, 9840284, 9840285, 9840286, 9840287, 9840288, 9840289, 9840290, 9840291, 9840292, 9840293, 9840294, 9840295, 9840296, 9840297, 9840298, 9840299, 9840300, 9840301, 9840302, 9840303, 9840304, 9840305, 9840306, 9840307, 9840308, 9840309, 9840310, 9840311, 9840312, 9840313, 9840314, 9840315, 9840316, 9840317, 9840318, 9840319, 9840320, 9840321, 9840322, 9840323, 9840324, 9840325, 9840326, 9840327, 9840328, 9840329, 9840330, 9840331, 9840332, 9840333, 9840334, 9840335, 9840336, 9840337, 9840338, 9840339, 9840340, 9840341, 9840342, 9840343, 9840344, 9840345, 9840346, 9840347, 9840348, 9840349, 9840350, 9840351, 9840352, 9840353, 9840354, 9840355, 9840356, 9840357, 9840358, 9840359, 9840360, 9840361, 9840362, 9840363, 9840364, 9840365, 9840366, 9840367, 9840368, 9840369, 9840370, 9840371, 9840372, 9840373, 9840374, 9840375, 9840376, 9840377, 9840378, 9840379, 9840380, 9840381, 9840382, 9840383, 9840384, 9840385, 9840386, 9840387, 9840388, 9840389, 9840390, 9840391, 9840392, 9840393, 9840394, 9840395, 9840396, 9840397, 9840398, 9840399, 9840400, 9840401, 9840402, 9840403, 9840404, 9840405, 9840406, 9840407, 9840408, 9840409, 9840410, 9840411, 9840412, 9840413, 9840414, 9840415, 9840416, 9840417, 9840418, 9840419, 9840420, 9840421, 9840422, 9840423, 9840424, 9840425, 9840426, 9840427, 9840428, 9840429, 9840430, 9840431, 9840432, 9840433, 9840434, 9840435, 9840436, 9840437, 9840438, 9840439, 9840440, 9840441, 9840442, 9840443, 9840444, 9840445, 9840446, 9840447, 9840448, 9840449, 9840450, 9840451, 9840452, 9840453, 9840454, 9840455, 9840456, 9840457, 9840458, 9840459, 9840460, 9840461, 9840462, 9840463, 9840464, 9840465, 9840466, 9840467, 9840468, 9840469, 9840470, 9840471, 9840472, 9840473, 9840474, 9840475, 9840476, 9840477, 9840478, 9840479, 9840480, 9840481, 9840482, 9840483, 9840484, 9840485, 9840486, 9840487, 9840488, 9840489, 9840490, 9840491, 9840492, 9840493, 9840494, 9840495, 9840496, 9840497, 9840498, 9840499, 9840500, 9840501, 9840502, 9840503, 9840504, 9840505, 9840506, 9840507, 9840508, 9840509, 9840510, 9840511, 9840512, 9840513, 9840514, 9840515, 9840516, 9840517, 9840518, 9840519, 9840520, 9840521, 9840522, 9840523, 9840524, 9840525, 9840526, 9840527, 9840528, 9840529, 9840530, 9840531, 9840532, 9840533, 9840534, 9840535, 9840536, 9840537, 9840538, 9840539, 9840540, 9840541, 9840542, 9840543, 9840544, 9840545, 9840546, 9840547, 9840548, 9840549, 9840550, 9840551, 9840552, 9840553, 9840554, 9840555, 9840556, 9840557, 9840558, 9840559, 9840560, 9840561, 9840562, 9840563, 9840564, 9840565, 9840566, 9840567, 9840568, 9840569, 9840570, 9840571, 9840572, 9840573, 9840574, 9840575, 9840576, 9840577, 9840578, 9840579, 9840580, 9840581, 9840582, 9840583, 9840584, 9840585, 9840586, 9840587, 9840588, 9840589, 9840590, 9840591, 9840592, 9840593, 9840594, 9840595, 9840596, 9840597, 9840598, 9840599, 9840600, 9840601, 9840602, 9840603, 9840604, 9840605, 9840606, 9840607, 9840608, 9840609, 9840610, 9840611, 9840612, 9840613, 9840614, 9840615, 9840616, 9840617, 9840618, 9840619, 9840620, 9840621, 9840622, 9840623, 9840624, 9840625, 9840626, 9840627, 9840628, 9840629, 9840630, 9840631, 9840632, 9840633, 9840634, 9840635, 9840636, 9840637, 9840638, 9840639, 9840640, 9840641, 9840642, 9840643, 9840644, 9840645, 9840646, 9840647, 9840648, 9840649, 9840650, 9840651, 9840652, 9840653, 9840654, 9840655, 9840656, 9840657, 9840658, 9840659, 9840660, 9840661, 9840662, 9840663, 9840664, 9840665, 9840666, 9840667, 9840668, 9840669, 9840670, 9840671, 9840672, 9840673, 9840674, 9840675, 9840676, 9840677, 9840678, 9840679, 9840680, 9840681, 9840682, 9840683, 9840684, 9840685, 9840686, 9840687, 9840688, 9840689, 9840690, 9840691, 9840692, 9840693, 9840694, 9840695, 9840696, 9840697, 9840698, 9840699, 9840700, 9840701, 9840702, 9840703, 9840704, 9840705, 9840706, 9840707, 9840708, 9840709, 9840710, 9840711, 9840712, 9840713, 9840714, 9840715, 9840716, 9840717, 9840718, 9840719, 9840720, 9840721, 9840722, 9840723, 9840724, 9840725, 9840726, 9840727, 9840728, 9840729, 9840730, 9840731, 9840732, 9840733, 9840734, 9840735, 9840736, 9840737, 9840738, 9840739, 9840740, 9840741, 9840742, 9840743, 9840744, 9840745, 9840746, 9840747, 9840748, 9840749, 9840750, 9840751, 9840752, 9840753, 9840754, 9840755, 9840756, 9840757, 9840758, 9840759, 9840760, 9840761, 9840762, 9840763, 9840764, 9840765, 9840766, 9840767, 9840768, 9840769, 9840770, 9840771, 9840772, 9840773, 9840774, 9840775, 9840776, 9840777, 9840778, 9840779, 9840780, 9840781, 9840782, 9840783, 9840784, 9840785, 9840786, 9840787, 9840788, 9840789, 9840790, 9840791, 9840792, 9840793, 9840794, 9840795, 9840796, 9840797, 9840798, 9840799, 9840800, 9840801, 9840802, 9840803, 9840804, 9840805, 9840806, 9840807, 9840808, 9840809, 9840810, 9840811, 9840812, 9840813, 9840814, 9840815, 9840816, 9840817, 9840818, 9840819, 9840820, 9840821, 9840822, 9840823, 9840824, 9840825, 9840826, 9840827, 9840828, 9840829, 9840830, 9840831, 9840832, 9840833, 9840834, 9840835, 9840836, 9840837, 9840838, 9840839, 9840840, 9840841, 9840842, 9840843, 9840844, 9840845, 9840846, 9840847, 9840848, 9840849, 9840850, 9840851, 9840852, 9840853, 9840854, 9840855, 9840856, 9840857, 9840858, 9840859, 9840860, 9840861, 9840862, 9840863, 9840864, 9840865, 9840866, 9840867, 9840868, 9840869, 9840870, 9840871, 9840872, 9840873, 9840874, 9840875, 9840876, 9840877, 9840878, 9840879, 9840880, 9840881, 9840882, 9840883, 9840884, 9840885, 9840886, 9840887, 9840888, 9840889, 9840890, 9840891, 9840892, 9840893, 9840894, 9840895, 9840896, 9840897, 9840898, 9840899, 9840900, 9840901, 9840902, 9840903, 9840904, 9840905, 9840906, 9840907, 9840908, 9840909, 9840910, 9840911, 9840912, 9840913, 9840914, 9840915, 9840916, 9840917, 9840918, 9840919, 9840920, 9840921, 9840922, 9840923, 9840924, 9840925, 9840926, 9840927, 9840928, 9840929, 9840930, 9840931, 9840932, 9840933, 9840934, 9840935, 9840936, 9840937, 9840938, 9840939, 9840940, 9840941, 9840942, 9840943, 9840944, 9840945, 9840946, 9840947, 9840948, 9840949, 9840950, 9840951, 9840952, 9840953, 9840954, 9840955, 9840956, 9840957, 9840958, 9840959, 9840960, 9840961, 9840962, 9840963, 9840964, 9840965, 9840966, 9840967, 9840968, 9840969, 9840970, 9840971, 9840972, 9840973, 9840974, 9840975, 9840976, 9840977, 9840978, 9840979, 9840980, 9840981, 9840982, 9840983, 9840984, 9840985, 9840986, 9840987, 9840988, 9840989, 9840990, 9840991, 9840992, 9840993, 9840994, 9840995, 9840996, 9840997, 9840998, 9840999, 9841000, 9841001, 9841002, 9841003, 9841004, 9841005, 9841006, 9841007, 9841008, 9841009, 9841010, 9841011, 9841012, 9841013, 9841014, 9841015, 9841016, 9841017, 9841018, 9841019, 9841020, 9841021, 9841022, 9841023, 9841024, 9841025, 9841026, 9841027, 9841028, 9841029, 9841030, 9841031, 9841032, 9841033, 9841034, 9841035, 9841036, 9841037, 9841038, 9841039, 9841040, 9841041, 9841042, 9841043, 9841044, 9841045, 9841046, 9841047, 9841048, 9841049, 9841050, 9841051, 9841052, 9841053, 9841054, 9841055, 9841056, 9841057, 9841058, 9841059, 9841060, 9841061, 9841062, 9841063, 9841064, 9841065, 9841066, 9841067, 9841068, 9841069, 9841070, 9841071, 9841072, 9841073, 9841074, 9841075, 9841076, 9841077, 9841078, 9841079, 9841080, 9841081, 9841082, 9841083, 9841084, 9841085, 9841086, 9841087, 9841088, 9841089, 9841090, 9841091, 9841092, 9841093, 9841094, 9841095, 9841096, 9841097, 9841098, 9841099, 9841100, 9841101, 9841102, 9841103, 9841104, 9841105, 9841106, 9841107, 9841108, 9841109, 9841110, 9841111, 9841112, 9841113, 9841114, 9841115, 9841116, 9841117, 9841118, 9841119, 9841120, 9841121, 9841122, 9841123, 9841124, 9841125, 9841126, 9841127, 9841128, 9841129, 9841130, 9841131, 9841132, 9841133, 9841134, 9841135, 9841136, 9841137, 9841138, 9841139, 9841140, 9841141, 9841142, 9841143, 9841144, 9841145, 9841146, 9841147, 9841148, 9841149, 9841150, 9841151, 9841152, 9841153, 9841154, 9841155, 9841156, 9841157, 9841158, 9841159, 9841160, 9841161, 9841162, 9841163, 9841164, 9841165, 9841166, 9841167, 9841168, 9841169, 9841170, 9841171, 9841172, 9841173, 9841174, 9841175, 9841176, 9841177, 9841178, 9841179, 9841180, 9841181, 9841182, 9841183, 9841184, 9841185, 9841186, 9841187, 9841188, 9841189, 9841190, 9841191, 9841192, 9841193, 9841194, 9841195, 9841196, 9841197, 9841198, 9841199, 9841200, 9841201, 9841202, 9841203, 9841204, 9841205, 9841206, 9841207, 9841208, 9841209, 9841210, 9841211, 9841212, 9841213, 9841214, 9841215, 9841216, 9841217, 9841218, 9841219, 9841220, 9841221, 9841222, 9841223, 9841224, 9841225, 9841226, 9841227, 9841228, 9841229, 9841230, 9841231, 9841232, 9841233, 9841234, 9841235, 9841236, 9841237, 9841238, 9841239, 9841240, 9841241, 9841242, 9841243, 9841244, 9841245, 9841246, 9841247, 9841248, 9841249, 9841250, 9841251, 9841252, 9841253, 9841254, 9841255, 9841256, 9841257, 9841258, 9841259, 9841260, 9841261, 9841262, 9841263, 9841264, 9841265, 9841266, 9841267, 9841268, 9841269, 9841270, 9841271, 9841272, 9841273, 9841274, 9841275, 9841276, 9841277, 9841278, 9841279, 9841280, 9841281, 9841282, 9841283, 9841284, 9841285, 9841286, 9841287, 9841288, 9841289, 9841290, 9841291, 9841292, 9841293, 9841294, 9841295, 9841296, 9841297, 9841298, 9841299, 9841300, 9841301, 9841302, 9841303, 9841304, 9841305, 9841306, 9841307, 9841308, 9841309, 9841310, 9841311, 9841312, 9841313, 9841314, 9841315, 9841316, 9841317, 9841318, 9841319, 9841320, 9841321, 9841322, 9841323, 9841324, 9841325, 9841326, 9841327, 9841328, 9841329, 9841330, 9841331, 9841332, 9841333, 9841334, 9841335, 9841336, 9841337, 9841338, 9841339, 9841340, 9841341, 9841342, 9841343, 9841344, 9841345, 9841346, 9841347, 9841348, 9841349, 9841350, 9841351, 9841352, 9841353, 9841354, 9841355, 9841356, 9841357, 9841358, 9841359, 9841360, 9841361, 9841362, 9841363, 9841364, 9841365, 9841366, 9841367, 9841368, 9841369, 9841370, 9841371, 9841372, 9841373, 9841374, 9841375, 9841376, 9841377, 9841378, 9841379, 9841380, 9841381, 9841382, 9841383, 9841384, 9841385, 9841386, 9841387, 9841388, 9841389, 9841390, 9841391, 9841392, 9841393, 9841394, 9841395, 9841396, 9841397, 9841398, 9841399, 9841400, 9841401, 9841402, 9841403, 9841404, 9841405, 9841406, 9841407, 9841408, 9841409, 9841410, 9841411, 9841412, 9841413, 9841414, 9841415, 9841416, 9841417, 9841418, 9841419, 9841420, 9841421, 9841422, 9841423, 9841424, 9841425, 9841426, 9841427, 9841428, 9841429, 9841430, 9841431, 9841432, 9841433, 9841434, 9841435, 9841436, 9841437, 9841438, 9841439, 9841440, 9841441, 9841442, 9841443, 9841444, 9841445, 9841446, 9841447, 9841448, 9841449, 9841450, 9841451, 9841452, 9841453, 9841454, 9841455, 9841456, 9841457, 9841458, 9841459, 9841460, 9841461, 9841462, 9841463, 9841464, 9841465, 9841466, 9841467, 9841468, 9841469, 9841470, 9841471, 9841472, 9841473, 9841474, 9841475, 9841476, 9841477, 9841478, 9841479, 9841480, 9841481, 9841482, 9841483, 9841484, 9841485, 9841486, 9841487, 9841488, 9841489, 9841490, 9841491, 9841492, 9841493, 9841494, 9841495, 9841496, 9841497, 9841498, 9841499, 9841500, 9841501, 9841502, 9841503, 9841504, 9841505, 9841506, 9841507, 9841508, 9841509, 9841510, 9841511, 9841512, 9841513, 9841514, 9841515, 9841516, 9841517, 9841518, 9841519, 9841520, 9841521, 9841522, 9841523, 9841524, 9841525, 9841526, 9841527, 9841528, 9841529, 9841530, 9841531, 9841532, 9841533, 9841534, 9841535, 9841536, 9841537, 9841538, 9841539, 9841540, 9841541, 9841542, 9841543, 9841544, 9841545, 9841546, 9841547, 9841548, 9841549, 9841550, 9841551, 9841552, 9841553, 9841554, 9841555, 9841556, 9841557, 9841558, 9841559, 9841560, 9841561, 9841562, 9841563, 9841564, 9841565, 9841566, 9841567, 9841568, 9841569, 9841570, 9841571, 9841572, 9841573, 9841574, 9841575, 9841576, 9841577, 9841578, 9841579, 9841580, 9841581, 9841582, 9841583, 9841584, 9841585, 9841586, 9841587, 9841588, 9841589, 9841590, 9841591, 9841592, 9841593, 9841594, 9841595, 9841596, 9841597, 9841598, 9841599, 9841600, 9841601, 9841602, 9841603, 9841604, 9841605, 9841606, 9841607, 9841608, 9841609, 9841610, 9841611, 9841612, 9841613, 9841614, 9841615, 9841616, 9841617, 9841618, 9841619, 9841620, 9841621, 9841622, 9841623, 9841624, 9841625, 9841626, 9841627, 9841628, 9841629, 9841630, 9841631, 9841632, 9841633, 9841634, 9841635, 9841636, 9841637, 9841638, 9841639, 9841640, 9841641, 9841642, 9841643, 9841644, 9841645, 9841646, 9841647, 9841648, 9841649, 9841650, 9841651, 9841652, 9841653, 9841654, 9841655, 9841656, 9841657, 9841658, 9841659, 9841660, 9841661, 9841662, 9841663, 9841664, 9841665, 9841666, 9841667, 9841668, 9841669, 9841670, 9841671, 9841672, 9841673, 9841674, 9841675, 9841676, 9841677, 9841678, 9841679, 9841680, 9841681, 9841682, 9841683, 9841684, 9841685, 9841686, 9841687, 9841688, 9841689, 9841690, 9841691, 9841692, 9841693, 9841694, 9841695, 9841696, 9841697, 9841698, 9841699, 9841700, 9841701, 9841702, 9841703, 9841704, 9841705, 9841706, 9841707, 9841708, 9841709, 9841710, 9841711, 9841712, 9841713, 9841714, 9841715, 9841716, 9841717, 9841718, 9841719, 9841720, 9841721, 9841722, 9841723, 9841724, 9841725, 9841726, 9841727, 9841728, 9841729, 9841730, 9841731, 9841732, 9841733, 9841734, 9841735, 9841736, 9841737, 9841738, 9841739, 9841740, 9841741, 9841742, 9841743, 9841744, 9841745, 9841746, 9841747, 9841748, 9841749, 9841750, 9841751, 9841752, 9841753, 9841754, 9841755, 9841756, 9841757, 9841758, 9841759, 9841760, 9841761, 9841762, 9841763, 9841764, 9841765, 9841766, 9841767, 9841768, 9841769, 9841770, 9841771, 9841772, 9841773, 9841774, 9841775, 9841776, 9841777, 9841778, 9841779, 9841780, 9841781, 9841782, 9841783, 9841784, 9841785, 9841786, 9841787, 9841788, 9841789, 9841790, 9841791, 9841792, 9841793, 9841794, 9841795, 9841796, 9841797, 9841798, 9841799, 9841800, 9841801, 9841802, 9841803, 9841804, 9841805, 9841806, 9841807, 9841808, 9841809, 9841810, 9841811, 9841812, 9841813, 9841814, 9841815, 9841816, 9841817, 9841818, 9841819, 9841820, 9841821, 9841822, 9841823, 9841824, 9841825, 9841826, 9841827, 9841828, 9841829, 9841830, 9841831, 9841832, 9841833, 9841834, 9841835, 9841836, 9841837, 9841838, 9841839, 9841840, 9841841, 9841842, 9841843, 9841844, 9841845, 9841846, 9841847, 9841848, 9841849, 9841850, 9841851, 9841852, 9841853, 9841854, 9841855, 9841856, 9841857, 9841858, 9841859, 9841860, 9841861, 9841862, 9841863, 9841864, 9841865, 9841866, 9841867, 9841868, 9841869, 9841870, 9841871, 9841872, 9841873, 9841874, 9841875, 9841876, 9841877, 9841878, 9841879, 9841880, 9841881, 9841882, 9841883, 9841884, 9841885, 9841886, 9841887, 9841888, 9841889, 9841890, 9841891, 9841892, 9841893, 9841894, 9841895, 9841896, 9841897, 9841898, 9841899, 9841900, 9841901, 9841902, 9841903, 9841904, 9841905, 9841906, 9841907, 9841908, 9841909, 9841910, 9841911, 9841912, 9841913, 9841914, 9841915, 9841916, 9841917, 9841918, 9841919, 9841920, 9841921, 9841922, 9841923, 9841924, 9841925, 9841926, 9841927, 9841928, 9841929, 9841930, 9841931, 9841932, 9841933, 9841934, 9841935, 9841936, 9841937, 9841938, 9841939, 9841940, 9841941, 9841942, 9841943, 9841944, 9841945, 9841946, 9841947, 9841948, 9841949, 9841950, 9841951, 9841952, 9841953, 9841954, 9841955, 9841956, 9841957, 9841958, 9841959, 9841960, 9841961, 9841962, 9841963, 9841964, 9841965, 9841966, 9841967, 9841968, 9841969, 9841970, 9841971, 9841972, 9841973, 9841974, 9841975, 9841976, 9841977, 9841978, 9841979, 9841980, 9841981, 9841982, 9841983, 9841984, 9841985, 9841986, 9841987, 9841988, 9841989, 9841990, 9841991, 9841992, 9841993, 9841994, 9841995, 9841996, 9841997, 9841998, 9841999, 9842000, 9842001, 9842002, 9842003, 9842004, 9842005, 9842006, 9842007, 9842008, 9842009, 9842010, 9842011, 9842012, 9842013, 9842014, 9842015, 9842016, 9842017, 9842018, 9842019, 9842020, 9842021, 9842022, 9842023, 9842024, 9842025, 9842026, 9842027, 9842028, 9842029, 9842030, 9842031, 9842032, 9842033, 9842034, 9842035, 9842036, 9842037, 9842038, 9842039, 9842040, 9842041, 9842042, 9842043, 9842044, 9842045, 9842046, 9842047, 9842048, 9842049, 9842050, 9842051, 9842052, 9842053, 9842054, 9842055, 9842056, 9842057, 9842058, 9842059, 9842060, 9842061, 9842062, 9842063, 9842064, 9842065, 9842066, 9842067, 9842068, 9842069, 9842070, 9842071, 9842072, 9842073, 9842074, 9842075, 9842076, 9842077, 9842078, 9842079, 9842080, 9842081, 9842082, 9842083, 9842084, 9842085, 9842086, 9842087, 9842088, 9842089, 9842090, 9842091, 9842092, 9842093, 9842094, 9842095, 9842096, 9842097, 9842098, 9842099, 9842100, 9842101, 9842102, 9842103, 9842104, 9842105, 9842106, 9842107, 9842108, 9842109, 9842110, 9842111, 9842112, 9842113, 9842114, 9842115, 9842116, 9842117, 9842118, 9842119, 9842120, 9842121, 9842122, 9842123, 9842124, 9842125, 9842126, 9842127, 9842128, 9842129, 9842130, 9842131, 9842132, 9842133, 9842134, 9842135, 9842136, 9842137, 9842138, 9842139, 9842140, 9842141, 9842142, 9842143, 9842144, 9842145, 9842146, 9842147, 9842148, 9842149, 9842150, 9842151, 9842152, 9842153, 9842154, 9842155, 9842156, 9842157, 9842158, 9842159, 9842160, 9842161, 9842162, 9842163, 9842164, 9842165, 9842166, 9842167, 9842168, 9842169, 9842170, 9842171, 9842172, 9842173, 9842174, 9842175, 9842176, 9842177, 9842178, 9842179, 9842180, 9842181, 9842182, 9842183, 9842184, 9842185, 9842186, 9842187, 9842188, 9842189, 9842190, 9842191, 9842192, 9842193, 9842194, 9842195, 9842196, 9842197, 9842198, 9842199, 9842200, 9842201, 9842202, 9842203, 9842204, 9842205, 9842206, 9842207, 9842208, 9842209, 9842210, 9842211, 9842212, 9842213, 9842214, 9842215, 9842216, 9842217, 9842218, 9842219, 9842220, 9842221, 9842222, 9842223, 9842224, 9842225, 9842226, 9842227, 9842228, 9842229, 9842230, 9842231, 9842232, 9842233, 9842234, 9842235, 9842236, 9842237, 9842238, 9842239, 9842240, 9842241, 9842242, 9842243, 9842244, 9842245, 9842246, 9842247, 9842248, 9842249, 9842250, 9842251, 9842252, 9842253, 9842254, 9842255, 9842256, 9842257, 9842258, 9842259, 9842260, 9842261, 9842262, 9842263, 9842264, 9842265, 9842266, 9842267, 9842268, 9842269, 9842270, 9842271, 9842272, 9842273, 9842274, 9842275, 9842276, 9842277, 9842278, 9842279, 9842280, 9842281, 9842282, 9842283, 9842284, 9842285, 9842286, 9842287, 9842288, 9842289, 9842290, 9842291, 9842292, 9842293, 9842294, 9842295, 9842296, 9842297, 9842298, 9842299, 9842300, 9842301, 9842302, 9842303, 9842304, 9842305, 9842306, 9842307, 9842308, 9842309, 9842310, 9842311, 9842312, 9842313, 9842314, 9842315, 9842316, 9842317, 9842318, 9842319, 9842320, 9842321, 9842322, 9842323, 9842324, 9842325, 9842326, 9842327, 9842328, 9842329, 9842330, 9842331, 9842332, 9842333, 9842334, 9842335, 9842336, 9842337, 9842338, 9842339, 9842340, 9842341, 9842342, 9842343, 9842344, 9842345, 9842346, 9842347, 9842348, 9842349, 9842350, 9842351, 9842352, 9842353, 9842354, 9842355, 9842356, 9842357, 9842358, 9842359, 9842360, 9842361, 9842362, 9842363, 9842364, 9842365, 9842366, 9842367, 9842368, 9842369, 9842370, 9842371, 9842372, 9842373, 9842374, 9842375, 9842376, 9842377, 9842378, 9842379, 9842380, 9842381, 9842382, 9842383, 9842384, 9842385, 9842386, 9842387, 9842388, 9842389, 9842390, 9842391, 9842392, 9842393, 9842394, 9842395, 9842396, 9842397, 9842398, 9842399, 9842400, 9842401, 9842402, 9842403, 9842404, 9842405, 9842406, 9842407, 9842408, 9842409, 9842410, 9842411, 9842412, 9842413, 9842414, 9842415, 9842416, 9842417, 9842418, 9842419, 9842420, 9842421, 9842422, 9842423, 9842424, 9842425, 9842426, 9842427, 9842428, 9842429, 9842430, 9842431, 9842432, 9842433, 9842434, 9842435, 9842436, 9842437, 9842438, 9842439, 9842440, 9842441, 9842442, 9842443, 9842444, 9842445, 9842446, 9842447, 9842448, 9842449, 9842450, 9842451, 9842452, 9842453, 9842454, 9842455, 9842456, 9842457, 9842458, 9842459, 9842460, 9842461, 9842462, 9842463, 9842464, 9842465, 9842466, 9842467, 9842468, 9842469, 9842470, 9842471, 9842472, 9842473, 9842474, 9842475, 9842476, 9842477, 9842478, 9842479, 9842480, 9842481, 9842482, 9842483, 9842484, 9842485, 9842486, 9842487, 9842488, 9842489, 9842490, 9842491, 9842492, 9842493, 9842494, 9842495, 9842496, 9842497, 9842498, 9842499, 9842500, 9842501, 9842502, 9842503, 9842504, 9842505, 9842506, 9842507, 9842508, 9842509, 9842510, 9842511, 9842512, 9842513, 9842514, 9842515, 9842516, 9842517, 9842518, 9842519, 9842520, 9842521, 9842522, 9842523, 9842524, 9842525, 9842526, 9842527, 9842528, 9842529, 9842530, 9842531, 9842532, 9842533, 9842534, 9842535, 9842536, 9842537, 9842538, 9842539, 9842540, 9842541, 9842542, 9842543, 9842544, 9842545, 9842546, 9842547, 9842548, 9842549, 9842550, 9842551, 9842552, 9842553, 9842554, 9842555, 9842556, 9842557, 9842558, 9842559, 9842560, 9842561, 9842562, 9842563, 9842564, 9842565, 9842566, 9842567, 9842568, 9842569, 9842570, 9842571, 9842572, 9842573, 9842574, 9842575, 9842576, 9842577, 9842578, 9842579, 9842580, 9842581, 9842582, 9842583, 9842584, 9842585, 9842586, 9842587, 9842588, 9842589, 9842590, 9842591, 9842592, 9842593, 9842594, 9842595, 9842596, 9842597, 9842598, 9842599, 9842600, 9842601, 9842602, 9842603, 9842604, 9842605, 9842606, 9842607, 9842608, 9842609, 9842610, 9842611, 9842612, 9842613, 9842614, 9842615, 9842616, 9842617, 9842618, 9842619, 9842620, 9842621, 9842622, 9842623, 9842624, 9842625, 9842626, 9842627, 9842628, 9842629, 9842630, 9842631, 9842632, 9842633, 9842634, 9842635, 9842636, 9842637, 9842638, 9842639, 9842640, 9842641, 9842642, 9842643, 9842644, 9842645, 9842646, 9842647, 9842648, 9842649, 9842650, 9842651, 9842652, 9842653, 9842654, 9842655, 9842656, 9842657, 9842658, 9842659, 9842660, 9842661, 9842662, 9842663, 9842664, 9842665, 9842666, 9842667, 9842668, 9842669, 9842670, 9842671, 9842672, 9842673, 9842674, 9842675, 9842676, 9842677, 9842678, 9842679, 9842680, 9842681, 9842682, 9842683, 9842684, 9842685, 9842686, 9842687, 9842688, 9842689, 9842690, 9842691, 9842692, 9842693, 9842694, 9842695, 9842696, 9842697, 9842698, 9842699, 9842700, 9842701, 9842702, 9842703, 9842704, 9842705, 9842706, 9842707, 9842708, 9842709, 9842710, 9842711, 9842712, 9842713, 9842714, 9842715, 9842716, 9842717, 9842718, 9842719, 9842720, 9842721, 9842722, 9842723, 9842724, 9842725, 9842726, 9842727, 9842728, 9842729, 9842730, 9842731, 9842732, 9842733, 9842734, 9842735, 9842736, 9842737, 9842738, 9842739, 9842740, 9842741, 9842742, 9842743, 9842744, 9842745, 9842746, 9842747, 9842748, 9842749, 9842750, 9842751, 9842752, 9842753, 9842754, 9842755, 9842756, 9842757, 9842758, 9842759, 9842760, 9842761, 9842762, 9842763, 9842764, 9842765, 9842766, 9842767, 9842768, 9842769, 9842770, 9842771, 9842772, 9842773, 9842774, 9842775, 9842776, 9842777, 9842778, 9842779, 9842780, 9842781, 9842782, 9842783, 9842784, 9842785, 9842786, 9842787, 9842788, 9842789, 9842790, 9842791, 9842792, 9842793, 9842794, 9842795, 9842796, 9842797, 9842798, 9842799, 9842800, 9842801, 9842802, 9842803, 9842804, 9842805, 9842806, 9842807, 9842808, 9842809, 9842810, 9842811, 9842812, 9842813, 9842814, 9842815, 9842816, 9842817, 9842818, 9842819, 9842820, 9842821, 9842822, 9842823, 9842824, 9842825, 9842826, 9842827, 9842828, 9842829, 9842830, 9842831, 9842832, 9842833, 9842834, 9842835, 9842836, 9842837, 9842838, 9842839, 9842840, 9842841, 9842842, 9842843, 9842844, 9842845, 9842846, 9842847, 9842848, 9842849, 9842850, 9842851, 9842852, 9842853, 9842854, 9842855, 9842856, 9842857, 9842858, 9842859, 9842860, 9842861, 9842862, 9842863, 9842864, 9842865, 9842866, 9842867, 9842868, 9842869, 9842870, 9842871, 9842872, 9842873, 9842874, 9842875, 9842876, 9842877, 9842878, 9842879, 9842880, 9842881, 9842882, 9842883, 9842884, 9842885, 9842886, 9842887, 9842888, 9842889, 9842890, 9842891, 9842892, 9842893, 9842894, 9842895, 9842896, 9842897, 9842898, 9842899, 9842900, 9842901, 9842902, 9842903, 9842904, 9842905, 9842906, 9842907, 9842908, 9842909, 9842910, 9842911, 9842912, 9842913, 9842914, 9842915, 9842916, 9842917, 9842918, 9842919, 9842920, 9842921, 9842922, 9842923, 9842924, 9842925, 9842926, 9842927, 9842928, 9842929, 9842930, 9842931, 9842932, 9842933, 9842934, 9842935, 9842936, 9842937, 9842938, 9842939, 9842940, 9842941, 9842942, 9842943, 9842944, 9842945, 9842946, 9842947, 9842948, 9842949, 9842950, 9842951, 9842952, 9842953, 9842954, 9842955, 9842956, 9842957, 9842958, 9842959, 9842960, 9842961, 9842962, 9842963, 9842964, 9842965, 9842966, 9842967, 9842968, 9842969, 9842970, 9842971, 9842972, 9842973, 9842974, 9842975, 9842976, 9842977, 9842978, 9842979, 9842980, 9842981, 9842982, 9842983, 9842984, 9842985, 9842986, 9842987, 9842988, 9842989, 9842990, 9842991, 9842992, 9842993, 9842994, 9842995, 9842996, 9842997, 9842998, 9842999, 9843000, 9843001, 9843002, 9843003, 9843004, 9843005, 9843006, 9843007, 9843008, 9843009, 9843010, 9843011, 9843012, 9843013, 9843014, 9843015, 9843016, 9843017, 9843018, 9843019, 9843020, 9843021, 9843022, 9843023, 9843024, 9843025, 9843026, 9843027, 9843028, 9843029, 9843030, 9843031, 9843032, 9843033, 9843034, 9843035, 9843036, 9843037, 9843038, 9843039, 9843040, 9843041, 9843042, 9843043, 9843044, 9843045, 9843046, 9843047, 9843048, 9843049, 9843050, 9843051, 9843052, 9843053, 9843054, 9843055, 9843056, 9843057, 9843058, 9843059, 9843060, 9843061, 9843062, 9843063, 9843064, 9843065, 9843066, 9843067, 9843068, 9843069, 9843070, 9843071, 9843072, 9843073, 9843074, 9843075, 9843076, 9843077, 9843078, 9843079, 9843080, 9843081, 9843082, 9843083, 9843084, 9843085, 9843086, 9843087, 9843088, 9843089, 9843090, 9843091, 9843092, 9843093, 9843094, 9843095, 9843096, 9843097, 9843098, 9843099, 9843100, 9843101, 9843102, 9843103, 9843104, 9843105, 9843106, 9843107, 9843108, 9843109, 9843110, 9843111, 9843112, 9843113, 9843114, 9843115, 9843116, 9843117, 9843118, 9843119, 9843120, 9843121, 9843122, 9843123, 9843124, 9843125, 9843126, 9843127, 9843128, 9843129, 9843130, 9843131, 9843132, 9843133, 9843134, 9843135, 9843136, 9843137, 9843138, 9843139, 9843140, 9843141, 9843142, 9843143, 9843144, 9843145, 9843146, 9843147, 9843148, 9843149, 9843150, 9843151, 9843152, 9843153, 9843154, 9843155, 9843156, 9843157, 9843158, 9843159, 9843160, 9843161, 9843162, 9843163, 9843164, 9843165, 9843166, 9843167, 9843168, 9843169, 9843170, 9843171, 9843172, 9843173, 9843174, 9843175, 9843176, 9843177, 9843178, 9843179, 9843180, 9843181, 9843182, 9843183, 9843184, 9843185, 9843186, 9843187, 9843188, 9843189, 9843190, 9843191, 9843192, 9843193, 9843194, 9843195, 9843196, 9843197, 9843198, 9843199, 9843200, 9843201, 9843202, 9843203, 9843204, 9843205, 9843206, 9843207, 9843208, 9843209, 9843210, 9843211, 9843212, 9843213, 9843214, 9843215, 9843216, 9843217, 9843218, 9843219, 9843220, 9843221, 9843222, 9843223, 9843224, 9843225, 9843226, 9843227, 9843228, 9843229, 9843230, 9843231, 9843232, 9843233, 9843234, 9843235, 9843236, 9843237, 9843238, 9843239, 9843240, 9843241, 9843242, 9843243, 9843244, 9843245, 9843246, 9843247, 9843248, 9843249, 9843250, 9843251, 9843252, 9843253, 9843254, 9843255, 9843256, 9843257, 9843258, 9843259, 9843260, 9843261, 9843262, 9843263, 9843264, 9843265, 9843266, 9843267, 9843268, 9843269, 9843270, 9843271, 9843272, 9843273, 9843274, 9843275, 9843276, 9843277, 9843278, 9843279, 9843280, 9843281, 9843282, 9843283, 9843284, 9843285, 9843286, 9843287, 9843288, 9843289, 9843290, 9843291, 9843292, 9843293, 9843294, 9843295, 9843296, 9843297, 9843298, 9843299, 9843300, 9843301, 9843302, 9843303, 9843304, 9843305, 9843306, 9843307, 9843308, 9843309, 9843310, 9843311, 9843312, 9843313, 9843314, 9843315, 9843316, 9843317, 9843318, 9843319, 9843320, 9843321, 9843322, 9843323, 9843324, 9843325, 9843326, 9843327, 9843328, 9843329, 9843330, 9843331, 9843332, 9843333, 9843334, 9843335, 9843336, 9843337, 9843338, 9843339, 9843340, 9843341, 9843342, 9843343, 9843344, 9843345, 9843346, 9843347, 9843348, 9843349, 9843350, 9843351, 9843352, 9843353, 9843354, 9843355, 9843356, 9843357, 9843358, 9843359, 9843360, 9843361, 9843362, 9843363, 9843364, 9843365, 9843366, 9843367, 9843368, 9843369, 9843370, 9843371, 9843372, 9843373, 9843374, 9843375, 9843376, 9843377, 9843378, 9843379, 9843380, 9843381, 9843382, 9843383, 9843384, 9843385, 9843386, 9843387, 9843388, 9843389, 9843390, 9843391, 9843392, 9843393, 9843394, 9843395, 9843396, 9843397, 9843398, 9843399, 9843400, 9843401, 9843402, 9843403, 9843404, 9843405, 9843406, 9843407, 9843408, 9843409, 9843410, 9843411, 9843412, 9843413, 9843414, 9843415, 9843416, 9843417, 9843418, 9843419, 9843420, 9843421, 9843422, 9843423, 9843424, 9843425, 9843426, 9843427, 9843428, 9843429, 9843430, 9843431, 9843432, 9843433, 9843434, 9843435, 9843436, 9843437, 9843438, 9843439, 9843440, 9843441, 9843442, 9843443, 9843444, 9843445, 9843446, 9843447, 9843448, 9843449, 9843450, 9843451, 9843452, 9843453, 9843454, 9843455, 9843456, 9843457, 9843458, 9843459, 9843460, 9843461, 9843462, 9843463, 9843464, 9843465, 9843466, 9843467, 9843468, 9843469, 9843470, 9843471, 9843472, 9843473, 9843474, 9843475, 9843476, 9843477, 9843478, 9843479, 9843480, 9843481, 9843482, 9843483, 9843484, 9843485, 9843486, 9843487, 9843488, 9843489, 9843490, 9843491, 9843492, 9843493, 9843494, 9843495, 9843496, 9843497, 9843498, 9843499, 9843500, 9843501, 9843502, 9843503, 9843504, 9843505, 9843506, 9843507, 9843508, 9843509, 9843510, 9843511, 9843512, 9843513, 9843514, 9843515, 9843516, 9843517, 9843518, 9843519, 9843520, 9843521, 9843522, 9843523, 9843524, 9843525, 9843526, 9843527, 9843528, 9843529, 9843530, 9843531, 9843532, 9843533, 9843534, 9843535, 9843536, 9843537, 9843538, 9843539, 9843540, 9843541, 9843542, 9843543, 9843544, 9843545, 9843546, 9843547, 9843548, 9843549, 9843550, 9843551, 9843552, 9843553, 9843554, 9843555, 9843556, 9843557, 9843558, 9843559, 9843560, 9843561, 9843562, 9843563, 9843564, 9843565, 9843566, 9843567, 9843568, 9843569, 9843570, 9843571, 9843572, 9843573, 9843574, 9843575, 9843576, 9843577, 9843578, 9843579, 9843580, 9843581, 9843582, 9843583, 9843584, 9843585, 9843586, 9843587, 9843588, 9843589, 9843590, 9843591, 9843592, 9843593, 9843594, 9843595, 9843596, 9843597, 9843598, 9843599, 9843600, 9843601, 9843602, 9843603, 9843604, 9843605, 9843606, 9843607, 9843608, 9843609, 9843610, 9843611, 9843612, 9843613, 9843614, 9843615, 9843616, 9843617, 9843618, 9843619, 9843620, 9843621, 9843622, 9843623, 9843624, 9843625, 9843626, 9843627, 9843628, 9843629, 9843630, 9843631, 9843632, 9843633, 9843634, 9843635, 9843636, 9843637, 9843638, 9843639, 9843640, 9843641, 9843642, 9843643, 9843644, 9843645, 9843646, 9843647, 9843648, 9843649, 9843650, 9843651, 9843652, 9843653, 9843654, 9843655, 9843656, 9843657, 9843658, 9843659, 9843660, 9843661, 9843662, 9843663, 9843664, 9843665, 9843666, 9843667, 9843668, 9843669, 9843670, 9843671, 9843672, 9843673, 9843674, 9843675, 9843676, 9843677, 9843678, 9843679, 9843680, 9843681, 9843682, 9843683, 9843684, 9843685, 9843686, 9843687, 9843688, 9843689, 9843690, 9843691, 9843692, 9843693, 9843694, 9843695, 9843696, 9843697, 9843698, 9843699, 9843700, 9843701, 9843702, 9843703, 9843704, 9843705, 9843706, 9843707, 9843708, 9843709, 9843710, 9843711, 9843712, 9843713, 9843714, 9843715, 9843716, 9843717, 9843718, 9843719, 9843720, 9843721, 9843722, 9843723, 9843724, 9843725, 9843726, 9843727, 9843728, 9843729, 9843730, 9843731, 9843732, 9843733, 9843734, 9843735, 9843736, 9843737, 9843738, 9843739, 9843740, 9843741, 9843742, 9843743, 9843744, 9843745, 9843746, 9843747, 9843748, 9843749, 9843750, 9843751, 9843752, 9843753, 9843754, 9843755, 9843756, 9843757, 9843758, 9843759, 9843760, 9843761, 9843762, 9843763, 9843764, 9843765, 9843766, 9843767, 9843768, 9843769, 9843770, 9843771, 9843772, 9843773, 9843774, 9843775, 9843776, 9843777, 9843778, 9843779, 9843780, 9843781, 9843782, 9843783, 9843784, 9843785, 9843786, 9843787, 9843788, 9843789, 9843790, 9843791, 9843792, 9843793, 9843794, 9843795, 9843796, 9843797, 9843798, 9843799, 9843800, 9843801, 9843802, 9843803, 9843804, 9843805, 9843806, 9843807, 9843808, 9843809, 9843810, 9843811, 9843812, 9843813, 9843814, 9843815, 9843816, 9843817, 9843818, 9843819, 9843820, 9843821, 9843822, 9843823, 9843824, 9843825, 9843826, 9843827, 9843828, 9843829, 9843830, 9843831, 9843832, 9843833, 9843834, 9843835, 9843836, 9843837, 9843838, 9843839, 9843840, 9843841, 9843842, 9843843, 9843844, 9843845, 9843846, 9843847, 9843848, 9843849, 9843850, 9843851, 9843852, 9843853, 9843854, 9843855, 9843856, 9843857, 9843858, 9843859, 9843860, 9843861, 9843862, 9843863, 9843864, 9843865, 9843866, 9843867, 9843868, 9843869, 9843870, 9843871, 9843872, 9843873, 9843874, 9843875, 9843876, 9843877, 9843878, 9843879, 9843880, 9843881, 9843882, 9843883, 9843884, 9843885, 9843886, 9843887, 9843888, 9843889, 9843890, 9843891, 9843892, 9843893, 9843894, 9843895, 9843896, 9843897, 9843898, 9843899, 9843900, 9843901, 9843902, 9843903, 9843904, 9843905, 9843906, 9843907, 9843908, 9843909, 9843910, 9843911, 9843912, 9843913, 9843914, 9843915, 9843916, 9843917, 9843918, 9843919, 9843920, 9843921, 9843922, 9843923, 9843924, 9843925, 9843926, 9843927, 9843928, 9843929, 9843930, 9843931, 9843932, 9843933, 9843934, 9843935, 9843936, 9843937, 9843938, 9843939, 9843940, 9843941, 9843942, 9843943, 9843944, 9843945, 9843946, 9843947, 9843948, 9843949, 9843950, 9843951, 9843952, 9843953, 9843954, 9843955, 9843956, 9843957, 9843958, 9843959, 9843960, 9843961, 9843962, 9843963, 9843964, 9843965, 9843966, 9843967, 9843968, 9843969, 9843970, 9843971, 9843972, 9843973, 9843974, 9843975, 9843976, 9843977, 9843978, 9843979, 9843980, 9843981, 9843982, 9843983, 9843984, 9843985, 9843986, 9843987, 9843988, 9843989, 9843990, 9843991, 9843992, 9843993, 9843994, 9843995, 9843996, 9843997, 9843998, 9843999, 9844000, 9844001, 9844002, 9844003, 9844004, 9844005, 9844006, 9844007, 9844008, 9844009, 9844010, 9844011, 9844012, 9844013, 9844014, 9844015, 9844016, 9844017, 9844018, 9844019, 9844020, 9844021, 9844022, 9844023, 9844024, 9844025, 9844026, 9844027, 9844028, 9844029, 9844030, 9844031, 9844032, 9844033, 9844034, 9844035, 9844036, 9844037, 9844038, 9844039, 9844040, 9844041, 9844042, 9844043, 9844044, 9844045, 9844046, 9844047, 9844048, 9844049, 9844050, 9844051, 9844052, 9844053, 9844054, 9844055, 9844056, 9844057, 9844058, 9844059, 9844060, 9844061, 9844062, 9844063, 9844064, 9844065, 9844066, 9844067, 9844068, 9844069, 9844070, 9844071, 9844072, 9844073, 9844074, 9844075, 9844076, 9844077, 9844078, 9844079, 9844080, 9844081, 9844082, 9844083, 9844084, 9844085, 9844086, 9844087, 9844088, 9844089, 9844090, 9844091, 9844092, 9844093, 9844094, 9844095, 9844096, 9844097, 9844098, 9844099, 9844100, 9844101, 9844102, 9844103, 9844104, 9844105, 9844106, 9844107, 9844108, 9844109, 9844110, 9844111, 9844112, 9844113, 9844114, 9844115, 9844116, 9844117, 9844118, 9844119, 9844120, 9844121, 9844122, 9844123, 9844124, 9844125, 9844126, 9844127, 9844128, 9844129, 9844130, 9844131, 9844132, 9844133, 9844134, 9844135, 9844136, 9844137, 9844138, 9844139, 9844140, 9844141, 9844142, 9844143, 9844144, 9844145, 9844146, 9844147, 9844148, 9844149, 9844150, 9844151, 9844152, 9844153, 9844154, 9844155, 9844156, 9844157, 9844158, 9844159, 9844160, 9844161, 9844162, 9844163, 9844164, 9844165, 9844166, 9844167, 9844168, 9844169, 9844170, 9844171, 9844172, 9844173, 9844174, 9844175, 9844176, 9844177, 9844178, 9844179, 9844180, 9844181, 9844182, 9844183, 9844184, 9844185, 9844186, 9844187, 9844188, 9844189, 9844190, 9844191, 9844192, 9844193, 9844194, 9844195, 9844196, 9844197, 9844198, 9844199, 9844200, 9844201, 9844202, 9844203, 9844204, 9844205, 9844206, 9844207, 9844208, 9844209, 9844210, 9844211, 9844212, 9844213, 9844214, 9844215, 9844216, 9844217, 9844218, 9844219, 9844220, 9844221, 9844222, 9844223, 9844224, 9844225, 9844226, 9844227, 9844228, 9844229, 9844230, 9844231, 9844232, 9844233, 9844234, 9844235, 9844236, 9844237, 9844238, 9844239, 9844240, 9844241, 9844242, 9844243, 9844244, 9844245, 9844246, 9844247, 9844248, 9844249, 9844250, 9844251, 9844252, 9844253, 9844254, 9844255, 9844256, 9844257, 9844258, 9844259, 9844260, 9844261, 9844262, 9844263, 9844264, 9844265, 9844266, 9844267, 9844268, 9844269, 9844270, 9844271, 9844272, 9844273, 9844274, 9844275, 9844276, 9844277, 9844278, 9844279, 9844280, 9844281, 9844282, 9844283, 9844284, 9844285, 9844286, 9844287, 9844288, 9844289, 9844290, 9844291, 9844292, 9844293, 9844294, 9844295, 9844296, 9844297, 9844298, 9844299, 9844300, 9844301, 9844302, 9844303, 9844304, 9844305, 9844306, 9844307, 9844308, 9844309, 9844310, 9844311, 9844312, 9844313, 9844314, 9844315, 9844316, 9844317, 9844318, 9844319, 9844320, 9844321, 9844322, 9844323, 9844324, 9844325, 9844326, 9844327, 9844328, 9844329, 9844330, 9844331, 9844332, 9844333, 9844334, 9844335, 9844336, 9844337, 9844338, 9844339, 9844340, 9844341, 9844342, 9844343, 9844344, 9844345, 9844346, 9844347, 9844348, 9844349, 9844350, 9844351, 9844352, 9844353, 9844354, 9844355, 9844356, 9844357, 9844358, 9844359, 9844360, 9844361, 9844362, 9844363, 9844364, 9844365, 9844366, 9844367, 9844368, 9844369, 9844370, 9844371, 9844372, 9844373, 9844374, 9844375, 9844376, 9844377, 9844378, 9844379, 9844380, 9844381, 9844382, 9844383, 9844384, 9844385, 9844386, 9844387, 9844388, 9844389, 9844390, 9844391, 9844392, 9844393, 9844394, 9844395, 9844396, 9844397, 9844398, 9844399, 9844400, 9844401, 9844402, 9844403, 9844404, 9844405, 9844406, 9844407, 9844408, 9844409, 9844410, 9844411, 9844412, 9844413, 9844414, 9844415, 9844416, 9844417, 9844418, 9844419, 9844420, 9844421, 9844422, 9844423, 9844424, 9844425, 9844426, 9844427, 9844428, 9844429, 9844430, 9844431, 9844432, 9844433, 9844434, 9844435, 9844436, 9844437, 9844438, 9844439, 9844440, 9844441, 9844442, 9844443, 9844444, 9844445, 9844446, 9844447, 9844448, 9844449, 9844450, 9844451, 9844452, 9844453, 9844454, 9844455, 9844456, 9844457, 9844458, 9844459, 9844460, 9844461, 9844462, 9844463, 9844464, 9844465, 9844466, 9844467, 9844468, 9844469, 9844470, 9844471, 9844472, 9844473, 9844474, 9844475, 9844476, 9844477, 9844478, 9844479, 9844480, 9844481, 9844482, 9844483, 9844484, 9844485, 9844486, 9844487, 9844488, 9844489, 9844490, 9844491, 9844492, 9844493, 9844494, 9844495, 9844496, 9844497, 9844498, 9844499, 9844500, 9844501, 9844502, 9844503, 9844504, 9844505, 9844506, 9844507, 9844508, 9844509, 9844510, 9844511, 9844512, 9844513, 9844514, 9844515, 9844516, 9844517, 9844518, 9844519, 9844520, 9844521, 9844522, 9844523, 9844524, 9844525, 9844526, 9844527, 9844528, 9844529, 9844530, 9844531, 9844532, 9844533, 9844534, 9844535, 9844536, 9844537, 9844538, 9844539, 9844540, 9844541, 9844542, 9844543, 9844544, 9844545, 9844546, 9844547, 9844548, 9844549, 9844550, 9844551, 9844552, 9844553, 9844554, 9844555, 9844556, 9844557, 9844558, 9844559, 9844560, 9844561, 9844562, 9844563, 9844564, 9844565, 9844566, 9844567, 9844568, 9844569, 9844570, 9844571, 9844572, 9844573, 9844574, 9844575, 9844576, 9844577, 9844578, 9844579, 9844580, 9844581, 9844582, 9844583, 9844584, 9844585, 9844586, 9844587, 9844588, 9844589, 9844590, 9844591, 9844592, 9844593, 9844594, 9844595, 9844596, 9844597, 9844598, 9844599, 9844600, 9844601, 9844602, 9844603, 9844604, 9844605, 9844606, 9844607, 9844608, 9844609, 9844610, 9844611, 9844612, 9844613, 9844614, 9844615, 9844616, 9844617, 9844618, 9844619, 9844620, 9844621, 9844622, 9844623, 9844624, 9844625, 9844626, 9844627, 9844628, 9844629, 9844630, 9844631, 9844632, 9844633, 9844634, 9844635, 9844636, 9844637, 9844638, 9844639, 9844640, 9844641, 9844642, 9844643, 9844644, 9844645, 9844646, 9844647, 9844648, 9844649, 9844650, 9844651, 9844652, 9844653, 9844654, 9844655, 9844656, 9844657, 9844658, 9844659, 9844660, 9844661, 9844662, 9844663, 9844664, 9844665, 9844666, 9844667, 9844668, 9844669, 9844670, 9844671, 9844672, 9844673, 9844674, 9844675, 9844676, 9844677, 9844678, 9844679, 9844680, 9844681, 9844682, 9844683, 9844684, 9844685, 9844686, 9844687, 9844688, 9844689, 9844690, 9844691, 9844692, 9844693, 9844694, 9844695, 9844696, 9844697, 9844698, 9844699, 9844700, 9844701, 9844702, 9844703, 9844704, 9844705, 9844706, 9844707, 9844708, 9844709, 9844710, 9844711, 9844712, 9844713, 9844714, 9844715, 9844716, 9844717, 9844718, 9844719, 9844720, 9844721, 9844722, 9844723, 9844724, 9844725, 9844726, 9844727, 9844728, 9844729, 9844730, 9844731, 9844732, 9844733, 9844734, 9844735, 9844736, 9844737, 9844738, 9844739, 9844740, 9844741, 9844742, 9844743, 9844744, 9844745, 9844746, 9844747, 9844748, 9844749, 9844750, 9844751, 9844752, 9844753, 9844754, 9844755, 9844756, 9844757, 9844758, 9844759, 9844760, 9844761, 9844762, 9844763, 9844764, 9844765, 9844766, 9844767, 9844768, 9844769, 9844770, 9844771, 9844772, 9844773, 9844774, 9844775, 9844776, 9844777, 9844778, 9844779, 9844780, 9844781, 9844782, 9844783, 9844784, 9844785, 9844786, 9844787, 9844788, 9844789, 9844790, 9844791, 9844792, 9844793, 9844794, 9844795, 9844796, 9844797, 9844798, 9844799, 9844800, 9844801, 9844802, 9844803, 9844804, 9844805, 9844806, 9844807, 9844808, 9844809, 9844810, 9844811, 9844812, 9844813, 9844814, 9844815, 9844816, 9844817, 9844818, 9844819, 9844820, 9844821, 9844822, 9844823, 9844824, 9844825, 9844826, 9844827, 9844828, 9844829, 9844830, 9844831, 9844832, 9844833, 9844834, 9844835, 9844836, 9844837, 9844838, 9844839, 9844840, 9844841, 9844842, 9844843, 9844844, 9844845, 9844846, 9844847, 9844848, 9844849, 9844850, 9844851, 9844852, 9844853, 9844854, 9844855, 9844856, 9844857, 9844858, 9844859, 9844860, 9844861, 9844862, 9844863, 9844864, 9844865, 9844866, 9844867, 9844868, 9844869, 9844870, 9844871, 9844872, 9844873, 9844874, 9844875, 9844876, 9844877, 9844878, 9844879, 9844880, 9844881, 9844882, 9844883, 9844884, 9844885, 9844886, 9844887, 9844888, 9844889, 9844890, 9844891, 9844892, 9844893, 9844894, 9844895, 9844896, 9844897, 9844898, 9844899, 9844900, 9844901, 9844902, 9844903, 9844904, 9844905, 9844906, 9844907, 9844908, 9844909, 9844910, 9844911, 9844912, 9844913, 9844914, 9844915, 9844916, 9844917, 9844918, 9844919, 9844920, 9844921, 9844922, 9844923, 9844924, 9844925, 9844926, 9844927, 9844928, 9844929, 9844930, 9844931, 9844932, 9844933, 9844934, 9844935, 9844936, 9844937, 9844938, 9844939, 9844940, 9844941, 9844942, 9844943, 9844944, 9844945, 9844946, 9844947, 9844948, 9844949, 9844950, 9844951, 9844952, 9844953, 9844954, 9844955, 9844956, 9844957, 9844958, 9844959, 9844960, 9844961, 9844962, 9844963, 9844964, 9844965, 9844966, 9844967, 9844968, 9844969, 9844970, 9844971, 9844972, 9844973, 9844974, 9844975, 9844976, 9844977, 9844978, 9844979, 9844980, 9844981, 9844982, 9844983, 9844984, 9844985, 9844986, 9844987, 9844988, 9844989, 9844990, 9844991, 9844992, 9844993, 9844994, 9844995, 9844996, 9844997, 9844998, 9844999] |
| 完整逐局来源 | source-ledger.json |
| 冻结源码SHA | {'scripts/prism_cloud_storage_snapshot.py': 'b417e62c6aa2ce56ad2968ab0ac4c952b4a954514128a6923efc272129f5eb8c', 'scripts/prism_dsw_arena.py': '172b6f9edbb69b2d0fc139cd3ac4678d5f0392f97b59ebd09164467beda7b399', 'scripts/prism_match_details.py': '0f7fb79de0a65e60dfcb914716c99562fa44dd7673e6c1c0ea5ee4916ba11bc4', 'scripts/prism_notebook_arena.py': '84baf17c3e9fb31638bb5e56799ceffaec41b96a7a358b289023ab55a6f7b935', 'scripts/prism_notebook_report.py': 'bc7dd35146d795c28c8f8a7fb3910cfe3b832e88884de32b93a0d010ff6fd9ec', 'scripts/prism_ppo_fixed_eval.py': 'fb6683d0f0d91d92efafef1d136545b3dabf376e014e066b19beb43fe78aeacb'} |




## M67种子B最终c20未发布训练检查点 对阵 Prism Alpha v0.1.5



被测模型模式：greedy（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 10000/5000 | 5758/69/4173 | 57.5800% | 57.9250% | 56.6500% / 58.5400% | 57.0000% / 58.8750% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 5000 | 2971/32/1997 | 59.4200 | 59.7400 | 14.5276 | 13.7060 |
| P1（后手） | 5000 | 2787/37/2176 | 55.7400 | 56.1100 | 14.5236 | 13.7302 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.5256 | 13.7181 |
| VP/本人全部决策 | 0.5404 | 0.5103 |
| VP/本人Main | 0.5405 | 0.5104 |
| VP/全局ply | 0.2702 | 0.2552 |
| 永久折扣/购卡每局 | 11.8157 | 11.8037 |
| 贵族/局 | 0.4798 | 0.4420 |
| 获得贵族的对局% | 40.2900 | 36.7400 |
| 预留获取/局 | 3.3676 | 3.2909 |
| 预留买回/局 | 1.3792 | 1.2854 |
| 终局未买回预留/局 | 1.9884 | 2.0055 |
| 预留买回/获取%（总分母） | 40.9550 | 39.0592 |
| 购入0 VP卡/局 | 5.9593 | 6.0828 |
| 购入1 VP卡/局 | 2.0670 | 2.1050 |
| 购入2 VP卡/局 | 1.8526 | 1.8073 |
| 购入3 VP卡/局 | 0.8023 | 0.8413 |
| 购入4 VP卡/局 | 0.7654 | 0.6879 |
| 购入5 VP卡/局 | 0.3691 | 0.2794 |
| White折扣/局 | 2.4117 | 2.4085 |
| Blue折扣/局 | 2.1969 | 2.2573 |
| Green折扣/局 | 2.2904 | 2.3889 |
| Red折扣/局 | 2.4458 | 2.3365 |
| Black折扣/局 | 2.4709 | 2.4125 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 104365 / 38.8253% | 105183 / 39.1300% |
| buy_reserved | 13792 / 5.1308% | 12854 / 4.7819% |
| take_tokens | 116919 / 43.4955% | 117804 / 43.8252% |
| reserve_market | 33675 / 12.5276% | 32908 / 12.2424% |
| reserve_deck | 1 / 0.0004% | 1 / 0.0004% |
| choose_noble | 52 / 0.0193% | 50 / 0.0186% |
| pass | 3 / 0.0011% | 4 / 0.0015% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 537611 / 53.7611 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.8854 / 19.0000 / 27.0000 / 34.0000 / 1.7775 |
| Main轮均值 | 26.8755 |
| 绝对终局分差 | 3.5775 |
| 分差≤2对局% | 35.9000 |
| 对局监督墙钟秒：累计 / 均 / P95 | 5339.8148 / 0.5340 / 0.7535 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/campaigns/b/cycle-20-export/weights.json', 'sha256': 'e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-prism', '--weights', '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', '--seed', '67020001'], 'files': [{'path': '/mnt/workspace/splendor-m67-alpha-repeat/inputs/parent.json', 'sha256': '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'}], 'program': '/mnt/workspace/splendor-m67-alpha-repeat/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |

