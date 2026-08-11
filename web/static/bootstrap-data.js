window.__GOAI_BOOTSTRAP_DATA__ = (() => {
  const timeline = (...states) => [
    { event_type: "TASK_CREATED", payload: {} },
    ...states.map((to) => ({ event_type: "STATE_TRANSITION", payload: { to } })),
  ];

  const edge = (from, to, mode, condition) => {
    const item = { from, to, mode };
    if (condition) item.condition = condition;
    return item;
  };

  const artifact = (artifact_type, producer, artifact_id) => ({
    artifact_type,
    producer,
    schema_version: "1.0",
    artifact_id,
  });

  const evidence = (label, kind, digest) => ({
    label,
    kind,
    content_digest: digest,
  });

  const track1 = {
    task_id: "T1-codeops-demo",
    trace_id: "trace_t1_offline",
    state: "CLOSED",
    state_version: 14,
    provider: "fixture-local",
    agents: [
      "intake",
      "triage",
      "env_bootstrap",
      "repo_analyst",
      "plan",
      "executor",
      "verifier",
      "postmortem",
    ],
    skills: [
      "IssueFusion",
      "RepoMap",
      "RootCauseProbe",
      "RunbookRAG",
      "IncidentMemory",
      "SkillDistiller",
      "RiskGuard",
      "PolicyCheck",
      "JudgeCalibrator",
      "SafePatchExec",
      "VerifyAndReplay",
      "ResumeGuard",
    ],
    topologies: [
      {
        team_id: "codeops-control-tower",
        control_plane: "AgentTeamsControlPlane",
        edges: [
          edge("intake", "triage", "sequential"),
          edge("triage", "env_bootstrap", "sequential"),
          edge("env_bootstrap", "repo_analyst", "sequential"),
          edge("repo_analyst", "plan", "fan-in"),
          edge("plan", "executor", "approval-gated"),
          edge("executor", "verifier", "sequential"),
          edge("verifier", "executor", "bounded-repair", "failure_signature"),
          edge("verifier", "postmortem", "sequential"),
        ],
      },
    ],
    trace: timeline("RECEIVED", "INTENT_PARSED", "DIAGNOSING", "PATCHED", "VERIFYING", "RELEASE_READY", "POSTMORTEM", "CLOSED"),
    artifacts: [
      artifact("IssueCluster", "repo_analyst", "art_issue_cluster"),
      artifact("ChangePlan", "plan", "art_change_plan"),
      artifact("PatchBundle", "executor", "art_patch_bundle"),
      artifact("VerificationReport", "verifier", "art_verification_report"),
      artifact("SkillCandidate", "postmortem", "art_skill_candidate"),
    ],
    evidence: [
      evidence("trace review and failure signature", "postmortem", "t1trace001abc"),
      evidence("independent hidden verification attempt 1", "verification", "t1verify001bc"),
      evidence("independent hidden verification attempt 2", "verification", "t1verify002cd"),
      evidence("CI regression and user report", "verification", "t1ci0001def"),
      evidence("structured claim and prohibited actions", "claim-ledger", "t1claim001efg"),
    ],
    summary: {
      final_state: "CLOSED",
      attempts: 2,
      hidden_verification: "pass",
      execution_mode: "real-fixture-subprocess",
    },
    port_manifests: new Array(15).fill(null),
  };

  const commonTrack2Topology = [
    {
      team_id: "insurance-growth-attribution",
      control_plane: "AgentTeamsControlPlane",
      edges: [
        edge("intent", "metric_contract", "contract-gated"),
        edge("metric_contract", "data_acquisition", "read-only"),
        edge("data_acquisition", "diagnostic", "fan-in"),
        edge("diagnostic", "causal_evidence", "evidence-gated"),
        edge("causal_evidence", "experiment_planner", "approval-gated"),
        edge("experiment_planner", "monitor_review", "sequential"),
      ],
    },
  ];

  const sharedTrack2Agents = [
    "intent",
    "metric_contract",
    "data_acquisition",
    "diagnostic",
    "causal_evidence",
    "experiment_planner",
    "monitor_review",
  ];

  const sharedTrack2Skills = [
    "AnalysisIntent",
    "MetricContract",
    "DataQualityReport",
    "FeatureSet",
    "AttributionCandidateSet",
    "ExperimentSpec",
    "MonitoringReport",
    "ClaimLedger",
    "EvidenceReport",
    "FeaturePolicy",
  ];

  const makeCase = (task_id, state_version, summary, claim, readiness, metrics, decomposition, trace, evidenceRows, artifactRows) => ({
    task_id,
    trace_id: `${task_id}-trace`,
    state: "CLOSED",
    state_version,
    case: task_id.slice(-1),
    provider: null,
    agents: sharedTrack2Agents,
    skills: sharedTrack2Skills,
    topologies: commonTrack2Topology,
    trace,
    artifacts: artifactRows,
    evidence: evidenceRows,
    summary,
    claim,
    causal_readiness: readiness,
    metrics,
    decomposition,
  });

  const track2CommonMetrics = {
    baseline: {
      active: 1200,
      quoted: 530,
      applied: 213,
      paid: 112,
      issued: 66,
      net_premium: 62845.22,
      quote_rate: 0.441667,
      apply_rate: 0.401887,
      paid_rate: 0.525822,
      issue_rate: 0.589286,
      issued_user_rate: 0.055,
      avg_premium: 952.2,
    },
    current: {
      active: 1200,
      quoted: 505,
      applied: 218,
      paid: 110,
      issued: 64,
      net_premium: 61256.43,
      quote_rate: 0.420833,
      apply_rate: 0.431683,
      paid_rate: 0.504587,
      issue_rate: 0.581818,
      issued_user_rate: 0.053333,
      avg_premium: 957.13,
    },
  };

  const caseA = makeCase(
    "T2-case-A",
    12,
    { final_state: "CLOSED", claim_type: "descriptive_only", evidence_level: "L1/L2", causal_outcome: "DESCRIPTIVE_ONLY" },
    {
      claim_id: "claim-001",
      claim_type: "descriptive_only",
      evidence_level: "L1/L2",
      allowed_verbs: ["观察到", "同时出现", "对应"],
      prohibited_actions: ["声称导致", "自动触达个人", "直接上线配置"],
      uncertainty: "causal identification unavailable",
      statement: "当前只能说明指标变化与候选因素同时出现，不能断言因果。",
    },
    {
      outcome: "DESCRIPTIVE_ONLY",
      identification_strategy: "not identified",
    },
    track2CommonMetrics,
    {
      method: "fixed-order log-chain decomposition",
      baseline_premium: 62845.22,
      current_premium: 61256.43,
      unexplained_residual: 0.0,
    },
    timeline("RECEIVED", "METRIC_CONFIRMED", "DIAGNOSING", "EVIDENCE_GRADED", "DESCRIPTIVE_ONLY", "CLOSED"),
    [
      evidence("fixed-order log-chain decomposition", "analysis", "t2aev01"),
      evidence("metadata-derived five-layer readiness check", "causal-readiness", "t2aev02"),
      evidence("structured claim and prohibited actions", "claim-ledger", "t2aev03"),
      evidence("bounded experiment draft", "experiment", "t2aev04"),
      evidence("trace review and failure signature", "analysis", "t2aev05"),
    ],
    [
      artifact("ClaimLedger", "causal_evidence", "art_t2a_claim"),
      artifact("EvidenceReport", "causal_evidence", "art_t2a_evidence"),
      artifact("ExperimentSpec", "experiment_planner", "art_t2a_experiment"),
      artifact("MonitoringReport", "monitor_review", "art_t2a_monitor"),
    ]
  );

  const caseB = makeCase(
    "T2-case-B",
    6,
    { final_state: "CLOSED", claim_type: "descriptive_only", evidence_level: "L1/L2", causal_outcome: "DATA_INSUFFICIENT" },
    {
      claim_id: "claim-001",
      claim_type: "descriptive_only",
      evidence_level: "L1/L2",
      allowed_verbs: ["当前缺少", "需要补充"],
      prohibited_actions: ["声称导致", "自动触达个人", "直接上线配置"],
      uncertainty: "required evidence is missing",
      statement: "当前证据不足，必须补齐实验配置、观察窗口或结果数据后才能评估因果效应。",
    },
    {
      outcome: "DATA_INSUFFICIENT",
      identification_strategy: "not identified",
    },
    track2CommonMetrics,
    {
      method: "fixed-order log-chain decomposition",
      baseline_premium: 62845.22,
      current_premium: 61256.43,
      unexplained_residual: 0.0,
    },
    timeline("RECEIVED", "DATA_INSUFFICIENT", "DIAGNOSING", "EVIDENCE_GRADED", "REVIEWED", "CLOSED"),
    [
      evidence("fixed-order log-chain decomposition", "analysis", "t2bev01"),
      evidence("metadata-derived five-layer readiness check", "causal-readiness", "t2bev02"),
      evidence("structured claim and prohibited actions", "claim-ledger", "t2bev03"),
      evidence("bounded experiment draft", "experiment", "t2bev04"),
      evidence("trace review and failure signature", "analysis", "t2bev05"),
    ],
    [
      artifact("ClaimLedger", "causal_evidence", "art_t2b_claim"),
      artifact("EvidenceReport", "causal_evidence", "art_t2b_evidence"),
      artifact("ExperimentSpec", "experiment_planner", "art_t2b_experiment"),
      artifact("MonitoringReport", "monitor_review", "art_t2b_monitor"),
    ]
  );

  const caseC = makeCase(
    "T2-case-C",
    11,
    { final_state: "CLOSED", claim_type: "causal_effect", evidence_level: "L3", causal_outcome: "CAUSAL_READY" },
    {
      claim_id: "claim-001",
      claim_type: "causal_effect",
      evidence_level: "L3",
      allowed_verbs: ["估计", "在本实验中提升"],
      prohibited_actions: ["未经审批上线排序"],
      uncertainty: "95% CI attached",
      statement: "经验证的随机分配满足因果门禁，可报告本实验中的 ITT 估计与置信区间。",
    },
    {
      outcome: "CAUSAL_READY",
      identification_strategy: "randomized",
    },
    {
      baseline: {
        active: 1200,
        quoted: 475,
        applied: 199,
        paid: 99,
        issued: 55,
        net_premium: 51502.87,
        quote_rate: 0.395833,
        apply_rate: 0.418947,
        paid_rate: 0.497487,
        issue_rate: 0.555556,
        issued_user_rate: 0.045833,
        avg_premium: 936.42,
      },
      current: {
        active: 1200,
        quoted: 493,
        applied: 212,
        paid: 118,
        issued: 66,
        net_premium: 61470.68,
        quote_rate: 0.410833,
        apply_rate: 0.43002,
        paid_rate: 0.556604,
        issue_rate: 0.559322,
        issued_user_rate: 0.055,
        avg_premium: 931.37,
      },
    },
    {
      method: "fixed-order log-chain decomposition",
      baseline_premium: 51502.87,
      current_premium: 61470.68,
      unexplained_residual: 0.0,
    },
    timeline("RECEIVED", "DATA_VALIDATED", "DIAGNOSING", "CAUSAL_READY", "AWAITING_APPROVAL", "CLOSED"),
    [
      evidence("ITT estimate and confidence intervals", "analysis", "t2cev01"),
      evidence("bounded experiment draft", "experiment", "t2cev02"),
      evidence("metadata-derived five-layer readiness check", "causal-readiness", "t2cev03"),
      evidence("structured claim and prohibited actions", "claim-ledger", "t2cev04"),
      evidence("trace review and failure signature", "analysis", "t2cev05"),
    ],
    [
      artifact("ClaimLedger", "causal_evidence", "art_t2c_claim"),
      artifact("ExperimentSpec", "experiment_planner", "art_t2c_experiment"),
      artifact("MonitoringReport", "monitor_review", "art_t2c_monitor"),
      artifact("EvidenceReport", "causal_evidence", "art_t2c_evidence"),
    ]
  );

  const real = {
    task_id: "T2-real-uci-bank-marketing",
    trace_id: "trace_real_offline",
    state: "CLOSED",
    state_version: 5,
    real_data: true,
    case: "REAL",
    provider: "uci-official",
    agents: ["data_acquisition", "diagnostic", "causal_evidence"],
    skills: ["SchemaProfiler", "DataQualityGate", "SegmentProfiler", "CausalReadinessCheck", "ClaimPolicyGuard"],
    topologies: [
      {
        team_id: "uci-bank-marketing",
        control_plane: "AgentTeamsControlPlane",
        edges: [
          edge("data_acquisition", "diagnostic", "read-only"),
          edge("diagnostic", "causal_evidence", "evidence-gated"),
        ],
      },
    ],
    trace: timeline("RECEIVED", "DATA_VALIDATED", "DIAGNOSING", "EVIDENCE_GRADED", "DESCRIPTIVE_ONLY", "CLOSED"),
    artifacts: [
      artifact("SourceManifest", "data_acquisition", "art_real_source"),
      artifact("DataQualityReport", "data_acquisition", "art_real_quality"),
      artifact("FeaturePolicy", "diagnostic", "art_real_policy"),
      artifact("EvidenceReport", "causal_evidence", "art_real_readiness"),
      artifact("ClaimLedger", "causal_evidence", "art_real_claim"),
    ],
    evidence: [
      evidence("official UCI source and checksum", "source", "real01"),
      evidence("real-data schema and missingness audit", "data-quality", "real02"),
      evidence("pre-call leakage policy", "leakage", "real03"),
      evidence("observational causal-readiness refusal", "causal-readiness", "real04"),
      evidence("real-data claim boundary", "claim-ledger", "real05"),
    ],
    source: {
      dataset_id: "uci-bank-marketing",
      name: "UCI Bank Marketing",
      official_source: "https://archive.ics.uci.edu/static/public/222/data.csv",
      official_page: "https://archive.ics.uci.edu/dataset/222/bank+marketing",
      dataset_doi: "10.24432/C5K306",
      license: "CC BY 4.0",
      license_url: "https://creativecommons.org/licenses/by/4.0/",
      checksum_verified: true,
    },
    profile: {
      row_count: 45211,
      subscription_rate: 0.116985,
      missing_cells: 52124,
    },
    causal_readiness: {
      outcome: "DESCRIPTIVE_ONLY",
      identification_strategy: "not identified",
    },
    claim: {
      claim_id: "claim-real-001",
      claim_type: "descriptive_only",
      evidence_level: "L1/L2",
      allowed_verbs: ["观察到", "历史记录显示", "对应"],
      prohibited_actions: ["声称导致", "使用 duration 做呼叫前决策", "生成个人营销名单"],
      statement: "UCI 的 45211 条真实银行营销记录中，定期存款订阅率为 11.70%。该数据没有随机处理分配，且 duration 属于结果后变量，因此只能报告历史相关性，不能声称因果。",
    },
    summary: {
      final_state: "CLOSED",
      claim_type: "descriptive_only",
      evidence_level: "L1/L2",
      causal_outcome: "DESCRIPTIVE_ONLY",
    },
  };

  return {
    track1,
    track2: {
      A: caseA,
      B: caseB,
      C: caseC,
      REAL: real,
    },
  };
})();
