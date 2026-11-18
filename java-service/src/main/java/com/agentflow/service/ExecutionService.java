package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.common.PageResult;
import com.agentflow.dto.ExecuteRequest;
import com.agentflow.dto.ExecutionDetailVO;
import com.agentflow.dto.ExecutionSummaryVO;
import com.agentflow.dto.NodeLogVO;
import com.agentflow.dto.NodeStatusVO;
import com.agentflow.dto.RunResultVO;
import com.agentflow.entity.ExecutionNodeLog;
import com.agentflow.entity.ExecutionRecord;
import com.agentflow.entity.Workflow;
import com.agentflow.mapper.ExecutionNodeLogMapper;
import com.agentflow.mapper.ExecutionRecordMapper;
import com.agentflow.security.CurrentUser;
import com.agentflow.util.FlowValidator;
import com.agentflow.util.SseReader;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.http.HttpStatus;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CancellationException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

@Slf4j
@Service
public class ExecutionService {

    private static final String RUNNING = "RUNNING";
    private static final String SUCCESS = "SUCCESS";
    private static final String FAILED = "FAILED";
    private static final String CANCELED = "CANCELED";

    private final Map<String, RunningExecution> running = new ConcurrentHashMap<>();

    private final AiClient aiClient;
    private final WorkflowService workflowService;
    private final LlmProviderService llmProviderService;
    private final McpServerService mcpServerService;
    private final ExecutionRecordMapper recordMapper;
    private final ExecutionNodeLogMapper nodeLogMapper;
    private final ObjectMapper objectMapper;
    private final ThreadPoolTaskExecutor executor;
    private final ModelPricingService pricingService;
    private final MeterRegistry meterRegistry;

    public ExecutionService(
            AiClient aiClient,
            WorkflowService workflowService,
            LlmProviderService llmProviderService,
            McpServerService mcpServerService,
            ExecutionRecordMapper recordMapper,
            ExecutionNodeLogMapper nodeLogMapper,
            ObjectMapper objectMapper,
            @Qualifier("executionExecutor") ThreadPoolTaskExecutor executor,
            ModelPricingService pricingService,
            MeterRegistry meterRegistry) {
        this.aiClient = aiClient;
        this.workflowService = workflowService;
        this.llmProviderService = llmProviderService;
        this.mcpServerService = mcpServerService;
        this.recordMapper = recordMapper;
        this.nodeLogMapper = nodeLogMapper;
        this.objectMapper = objectMapper;
        this.executor = executor;
        this.pricingService = pricingService;
        this.meterRegistry = meterRegistry;
        Gauge.builder("agentflow.executions.running", running, map -> map.size())
                .description("当前正在执行的工作流数量")
                .register(meterRegistry);
    }

    public SseEmitter execute(Long workflowId, ExecuteRequest request, CurrentUser user) {
        Workflow workflow = workflowService.getEntity(workflowId, user);
        WorkflowService.FlowSelection selection = workflowService.flowForRun(workflow, false);
        JsonNode flow = selection.flow();
        FlowValidator.validate(flow);

        ExecutionRecord record = prepareRecord(workflow, request, user.id(), flow, selection.version());
        String payload = buildPayload(record.getRunId(), workflowId, flow, request, user);
        // Complete all permission/payload checks before creating a RUNNING record.
        recordMapper.insert(record);

        SseEmitter emitter = new SseEmitter(0L);
        Map<String, ExecutionNodeLog> logs = new ConcurrentHashMap<>();
        AtomicBoolean closed = new AtomicBoolean(false);
        emitter.onCompletion(() -> closed.set(true));
        emitter.onTimeout(() -> closed.set(true));
        emitter.onError(error -> closed.set(true));

        RunningExecution execution = new RunningExecution();
        running.put(record.getRunId(), execution);
        try {
            executor.execute(() -> stream(emitter, record, payload, logs, closed, execution));
        } catch (RuntimeException ex) {
            throw rejectExecution(record, execution, ex);
        }
        return emitter;
    }

    /** 取消执行：通知 ai-service 终止 LangGraph 任务并断开上游流。 */
    public void cancel(String runId, CurrentUser user) {
        ExecutionRecord record = requireRecord(runId, user);
        RunningExecution execution = running.get(runId);
        if (execution == null) {
            if (RUNNING.equals(record.getStatus())) {
                record.setStatus(CANCELED);
                record.setErrorMessage("已取消");
                record.setElapsedMs(elapsedSince(record));
                record.setFinishedAt(LocalDateTime.now());
                recordMapper.updateById(record);
            }
            return;
        }
        execution.cancel();
        try {
            aiClient.postJson("/v1/executions/" + runId + "/cancel", Map.of());
        } catch (Exception ex) {
            log.debug("cancel request to ai-service failed, runId={}: {}", runId, ex.getMessage());
        }
    }

    @Transactional
    public void delete(String runId, CurrentUser user) {
        ExecutionRecord record = requireRecord(runId, user);
        if (RUNNING.equals(record.getStatus()) || running.containsKey(runId)) {
            throw new BizException(4090, "请先取消执行并等待结束后再删除", HttpStatus.CONFLICT);
        }
        nodeLogMapper.delete(new LambdaQueryWrapper<ExecutionNodeLog>()
                .eq(ExecutionNodeLog::getRunId, runId));
        recordMapper.deleteById(record.getId());
    }

    public PageResult<ExecutionSummaryVO> page(long page, long size, Long workflowId, String status, CurrentUser user) {
        if (workflowId != null) {
            workflowService.getEntity(workflowId, user);
        }
        LambdaQueryWrapper<ExecutionRecord> query = new LambdaQueryWrapper<ExecutionRecord>()
                .eq(!"ADMIN".equals(user.role()), ExecutionRecord::getUserId, user.id())
                .eq(workflowId != null, ExecutionRecord::getWorkflowId, workflowId)
                .eq(status != null && !status.isBlank(), ExecutionRecord::getStatus, status)
                .orderByDesc(ExecutionRecord::getId);
        Page<ExecutionRecord> result = recordMapper.selectPage(new Page<>(page, size), query);
        List<ExecutionSummaryVO> records = result.getRecords().stream()
                .map(item -> ExecutionSummaryVO.builder()
                        .id(item.getId())
                        .runId(item.getRunId())
                        .workflowId(item.getWorkflowId())
                        .workflowName(item.getWorkflowName())
                        .status(item.getStatus())
                        .nodeCount(item.getNodeCount())
                        .flowVersion(item.getFlowVersion())
                        .promptTokens(item.getPromptTokens())
                        .completionTokens(item.getCompletionTokens())
                        .totalTokens(item.getTotalTokens())
                        .costUsd(item.getCostUsd())
                        .elapsedMs(item.getElapsedMs())
                        .errorMessage(item.getErrorMessage())
                        .startedAt(item.getStartedAt())
                        .finishedAt(item.getFinishedAt())
                        .build())
                .toList();
        return new PageResult<>(records, result.getTotal(), page, size);
    }

    public ExecutionDetailVO detail(String runId, CurrentUser user) {
        ExecutionRecord record = requireRecord(runId, user);
        List<ExecutionNodeLog> logs = nodeLogMapper.selectList(
                new LambdaQueryWrapper<ExecutionNodeLog>()
                        .eq(ExecutionNodeLog::getRunId, runId)
                        .orderByAsc(ExecutionNodeLog::getSeq));
        return ExecutionDetailVO.builder()
                .runId(record.getRunId())
                .workflowId(record.getWorkflowId())
                .workflowName(record.getWorkflowName())
                .status(record.getStatus())
                .flowVersion(record.getFlowVersion())
                .promptTokens(record.getPromptTokens())
                .completionTokens(record.getCompletionTokens())
                .totalTokens(record.getTotalTokens())
                .costUsd(record.getCostUsd())
                .input(record.getInputData())
                .output(record.getOutputData())
                .errorMessage(record.getErrorMessage())
                .elapsedMs(record.getElapsedMs())
                .startedAt(record.getStartedAt())
                .finishedAt(record.getFinishedAt())
                .nodes(logs.stream().map(NodeLogVO::from).toList())
                .build();
    }

    private void stream(SseEmitter emitter, ExecutionRecord record, String payload,
                        Map<String, ExecutionNodeLog> logs, AtomicBoolean closed, RunningExecution execution) {
        MDC.put("runId", record.getRunId());
        MDC.put("workflowId", String.valueOf(record.getWorkflowId()));
        log.info("execution started, workflowId={}, flowVersion={}", record.getWorkflowId(), record.getFlowVersion());
        try {
            execution.checkCanceled();
            try (InputStream input = aiClient.openExecution(payload)) {
                execution.attach(input);
                SseReader.read(input, (event, body) -> {
                    if (!closed.get()) {
                        try {
                            emitter.send(SseEmitter.event().name(event).data(body, MediaType.APPLICATION_JSON));
                        } catch (Exception sendError) {
                            closed.set(true);
                            log.info("client disconnected from run {}", record.getRunId());
                        }
                    }
                    handleEvent(record, logs, event, body);
                });
            }
            if (!closed.get()) {
                emitter.complete();
            }
        } catch (Exception ex) {
            if (execution.canceled.get()) {
                log.info("execution canceled, runId={}", record.getRunId());
                record.setStatus(CANCELED);
                record.setErrorMessage("已取消");
                record.setFinishedAt(LocalDateTime.now());
            } else {
                log.error("execution stream failed, runId={}", record.getRunId(), ex);
                if (record.getStatus().equals(RUNNING)) {
                    record.setStatus(FAILED);
                    record.setErrorMessage(ex.getMessage());
                    record.setFinishedAt(LocalDateTime.now());
                }
            }
            if (!closed.get()) {
                emitter.completeWithError(ex);
            }
        } finally {
            running.remove(record.getRunId(), execution);
            persist(record, logs, execution);
            MDC.remove("runId");
            MDC.remove("workflowId");
        }
    }

    /** 同步执行：消费 SSE 流直到结束，汇总为 JSON 返回（适合只关心最终结果的程序调用方）。 */
    public RunResultVO runSync(Long workflowId, ExecuteRequest request, CurrentUser user) {
        Workflow workflow = workflowService.getEntity(workflowId, user);
        WorkflowService.FlowSelection selection = workflowService.flowForRun(workflow, false);
        FlowValidator.validate(selection.flow());
        ExecutionRecord record = prepareRecord(workflow, request, user.id(),
                selection.flow(), selection.version());
        String payload = buildPayload(record.getRunId(), workflow.getId(), selection.flow(), request, user);
        recordMapper.insert(record);
        RunningExecution execution = new RunningExecution();
        running.put(record.getRunId(), execution);
        return executeRecord(record, payload, execution);
    }

    /**
     * 异步提交一次执行（供触发器使用），立即返回 runId；执行完成后回调 onFinish。
     * 不校验调用者归属，由触发器服务在提交前完成。
     */
    public String submit(Long workflowId, ExecuteRequest request, Long userId, Consumer<RunResultVO> onFinish) {
        return submit(workflowId, request, userId, false, onFinish);
    }

    /**
     * 异步提交一次执行。
     *
     * @param preferPublished true 时优先执行发布版本（触发器 / Webhook），
     *                        false 时执行当前草稿（编辑器手动运行）。
     */
    public String submit(Long workflowId, ExecuteRequest request, Long userId,
                         boolean preferPublished, Consumer<RunResultVO> onFinish) {
        Workflow workflow = workflowService.getEntity(workflowId);
        WorkflowService.FlowSelection selection = workflowService.flowForRun(workflow, preferPublished);
        FlowValidator.validate(selection.flow());
        ExecutionRecord record = prepareRecord(workflow, request, userId,
                selection.flow(), selection.version());
        CurrentUser owner = new CurrentUser(record.getUserId(), null, "USER");
        String payload = buildPayload(record.getRunId(), workflowId, selection.flow(), request, owner);
        recordMapper.insert(record);
        // Register before enqueuing: cancellation must also work for queued tasks.
        RunningExecution execution = new RunningExecution();
        running.put(record.getRunId(), execution);
        try {
            executor.execute(() -> {
                RunResultVO result = executeRecord(record, payload, execution);
                if (onFinish != null) {
                    try {
                        onFinish.accept(result);
                    } catch (Exception ex) {
                        log.warn("execution callback failed, runId={}: {}", record.getRunId(), ex.getMessage());
                    }
                }
            });
        } catch (RuntimeException ex) {
            throw rejectExecution(record, execution, ex);
        }
        return record.getRunId();
    }

    private ExecutionRecord prepareRecord(Workflow workflow, ExecuteRequest request, Long userId,
                                          JsonNode flow, Integer flowVersion) {
        ExecutionRecord record = new ExecutionRecord();
        record.setRunId(UUID.randomUUID().toString().replace("-", ""));
        record.setWorkflowId(workflow.getId());
        record.setWorkflowName(workflow.getName());
        record.setUserId(userId == null ? workflow.getUserId() : userId);
        record.setStatus(RUNNING);
        record.setNodeCount(FlowValidator.countNodes(flow));
        record.setFlowVersion(flowVersion);
        record.setPromptTokens(0);
        record.setCompletionTokens(0);
        record.setTotalTokens(0);
        record.setCostUsd(BigDecimal.ZERO);
        record.setElapsedMs(0L);
        record.setStartedAt(LocalDateTime.now());
        record.setInputData(writeJson(request.getInput() == null ? Map.of() : request.getInput()));
        return record;
    }

    private BizException rejectExecution(ExecutionRecord record, RunningExecution execution, RuntimeException cause) {
        running.remove(record.getRunId(), execution);
        record.setStatus(FAILED);
        record.setErrorMessage("执行线程池已满或已关闭，请稍后重试");
        record.setElapsedMs(elapsedSince(record));
        record.setFinishedAt(LocalDateTime.now());
        recordMapper.updateById(record);
        recordRunMetrics(record);
        log.warn("execution rejected, runId={}: {}", record.getRunId(), cause.getMessage());
        return new BizException(5030, record.getErrorMessage(), HttpStatus.SERVICE_UNAVAILABLE);
    }

    /** 消费一次 ai-service SSE 流并落库，返回汇总结果。 */
    private RunResultVO executeRecord(ExecutionRecord record, String payload, RunningExecution execution) {
        Map<String, ExecutionNodeLog> logs = new ConcurrentHashMap<>();
        MDC.put("runId", record.getRunId());
        MDC.put("workflowId", String.valueOf(record.getWorkflowId()));
        log.info("execution started, workflowId={}, flowVersion={}", record.getWorkflowId(), record.getFlowVersion());
        try {
            execution.checkCanceled();
            try (InputStream input = aiClient.openExecution(payload)) {
                execution.attach(input);
                SseReader.read(input, (event, body) -> handleEvent(record, logs, event, body));
            }
        } catch (Exception ex) {
            if (execution.canceled.get()) {
                record.setStatus(CANCELED);
                record.setErrorMessage("已取消");
                record.setFinishedAt(LocalDateTime.now());
            } else {
                log.error("execution failed, runId={}", record.getRunId(), ex);
                if (record.getStatus().equals(RUNNING)) {
                    record.setStatus(FAILED);
                    record.setErrorMessage(ex.getMessage());
                    record.setFinishedAt(LocalDateTime.now());
                }
            }
        } finally {
            running.remove(record.getRunId(), execution);
            persist(record, logs, execution);
            MDC.remove("runId");
            MDC.remove("workflowId");
        }
        return toRunResult(record, logs);
    }

    private RunResultVO toRunResult(ExecutionRecord record, Map<String, ExecutionNodeLog> logs) {
        List<NodeStatusVO> nodes = logs.values().stream()
                .sorted(Comparator.comparing(n -> n.getSeq() == null ? 0 : n.getSeq()))
                .map(n -> NodeStatusVO.builder()
                        .nodeId(n.getNodeId())
                        .nodeType(n.getNodeType())
                        .nodeName(n.getNodeName())
                        .status(n.getStatus())
                        .output(parseJson(n.getOutputData()))
                        .elapsedMs(n.getElapsedMs())
                        .errorMessage(n.getErrorMessage())
                        .build())
                .toList();
        return RunResultVO.builder()
                .runId(record.getRunId())
                .status(record.getStatus())
                .outputs(parseJson(record.getOutputData()))
                .nodeStatus(nodes)
                .promptTokens(record.getPromptTokens())
                .completionTokens(record.getCompletionTokens())
                .totalTokens(record.getTotalTokens())
                .costUsd(record.getCostUsd())
                .elapsedMs(record.getElapsedMs())
                .errorMessage(record.getErrorMessage())
                .build();
    }

    private Object parseJson(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(json, Object.class);
        } catch (Exception ex) {
            return null;
        }
    }

    private void handleEvent(ExecutionRecord record, Map<String, ExecutionNodeLog> logs, String event, String body) {
        try {
            JsonNode node = objectMapper.readTree(body);
            switch (event) {
                case "node_started" -> {
                    ExecutionNodeLog log = new ExecutionNodeLog();
                    log.setRunId(record.getRunId());
                    log.setWorkflowId(record.getWorkflowId());
                    log.setNodeId(node.path("nodeId").asText());
                    log.setNodeType(node.path("nodeType").asText());
                    log.setNodeName(node.path("nodeName").asText());
                    log.setSeq(node.path("seq").asInt());
                    log.setStatus(RUNNING);
                    log.setStartedAt(LocalDateTime.now());
                    logs.put(log.getNodeId(), log);
                }
                case "node_finished" -> {
                    ExecutionNodeLog log = logs.get(node.path("nodeId").asText());
                    if (log != null) {
                        log.setStatus(SUCCESS);
                        log.setOutputData(writeJson(node.path("output")));
                        log.setElapsedMs(node.path("elapsedMs").asLong());
                        log.setFinishedAt(LocalDateTime.now());
                        applyUsage(record, node.path("output"));
                        recordNodeMetrics(log, SUCCESS);
                    }
                }
                case "node_failed" -> {
                    ExecutionNodeLog log = logs.get(node.path("nodeId").asText());
                    if (log != null) {
                        log.setStatus(FAILED);
                        log.setErrorMessage(node.path("error").path("message").asText("执行失败"));
                        log.setElapsedMs(node.path("elapsedMs").asLong());
                        log.setFinishedAt(LocalDateTime.now());
                        recordNodeMetrics(log, FAILED);
                    }
                }
                case "run_finished" -> {
                    record.setStatus(SUCCESS);
                    record.setOutputData(writeJson(node.path("output")));
                    record.setElapsedMs(node.path("elapsedMs").asLong());
                    record.setFinishedAt(LocalDateTime.now());
                }
                case "run_failed" -> {
                    record.setStatus(FAILED);
                    record.setErrorMessage(node.path("error").path("message").asText("执行失败"));
                    record.setElapsedMs(node.path("elapsedMs").asLong());
                    record.setFinishedAt(LocalDateTime.now());
                }
                default -> {
                    // run_started / node_token / node_log / done are forwarded only
                }
            }
        } catch (Exception ex) {
            log.warn("failed to handle event {}: {}", event, ex.getMessage());
        }
    }

    private void persist(ExecutionRecord record, Map<String, ExecutionNodeLog> logs, RunningExecution execution) {
        try {
            if (RUNNING.equals(record.getStatus())) {
                record.setStatus(execution.canceled.get() ? CANCELED : FAILED);
                record.setErrorMessage(execution.canceled.get() ? "已取消" : "执行中断");
            }
            if (record.getFinishedAt() == null) {
                record.setFinishedAt(LocalDateTime.now());
            }
            if (!SUCCESS.equals(record.getStatus())) {
                record.setElapsedMs(elapsedSince(record));
            }
            List<ExecutionNodeLog> ordered = new ArrayList<>(logs.values());
            ordered.sort(Comparator.comparing(item -> item.getSeq() == null ? 0 : item.getSeq()));
            for (ExecutionNodeLog log : ordered) {
                if (RUNNING.equals(log.getStatus())) {
                    log.setStatus(CANCELED.equals(record.getStatus()) ? CANCELED : FAILED);
                    log.setErrorMessage(record.getErrorMessage());
                    log.setFinishedAt(record.getFinishedAt());
                    log.setElapsedMs(Math.max(0, Duration.between(log.getStartedAt(), log.getFinishedAt()).toMillis()));
                    recordNodeMetrics(log, log.getStatus());
                }
                nodeLogMapper.insert(log);
            }
            recordMapper.updateById(record);
            recordRunMetrics(record);
            log.info("execution finished, status={}, elapsedMs={}, tokens={}, cost={}",
                    record.getStatus(), record.getElapsedMs(), record.getTotalTokens(), record.getCostUsd());
        } catch (Exception ex) {
            log.error("failed to persist execution {}, runId={}", record.getId(), record.getRunId(), ex);
        }
    }

    private void recordRunMetrics(ExecutionRecord record) {
        String status = record.getStatus() == null ? "UNKNOWN" : record.getStatus();
        meterRegistry.counter("agentflow.executions", "status", status).increment();
        Timer.builder("agentflow.execution.duration")
                .description("工作流执行耗时")
                .tag("status", status)
                .register(meterRegistry)
                .record(Duration.ofMillis(record.getElapsedMs() == null ? 0 : record.getElapsedMs()));
    }

    private void recordNodeMetrics(ExecutionNodeLog log, String status) {
        if (log == null) {
            return;
        }
        String type = log.getNodeType() == null || log.getNodeType().isBlank() ? "unknown" : log.getNodeType();
        meterRegistry.counter("agentflow.nodes", "type", type, "status", status).increment();
        Timer.builder("agentflow.node.duration")
                .tag("type", type)
                .tag("status", status)
                .register(meterRegistry)
                .record(Duration.ofMillis(log.getElapsedMs() == null ? 0 : log.getElapsedMs()));
    }

    /** 从节点输出里的 usage 汇总 token 与估算成本，并记录按模型的 token 指标。 */
    private void applyUsage(ExecutionRecord record, JsonNode output) {
        JsonNode usage = output.path("usage");
        if (!usage.isObject()) {
            return;
        }
        int prompt = firstInt(usage, "promptTokens", "prompt_tokens", "input_tokens", "inputTokens");
        int completion = firstInt(usage, "completionTokens", "completion_tokens", "output_tokens", "outputTokens");
        int total = firstInt(usage, "totalTokens", "total_tokens");
        if (total <= 0) {
            total = prompt + completion;
        }
        if (prompt == 0 && completion == 0 && total == 0) {
            return;
        }
        record.setPromptTokens(nvl(record.getPromptTokens()) + prompt);
        record.setCompletionTokens(nvl(record.getCompletionTokens()) + completion);
        record.setTotalTokens(nvl(record.getTotalTokens()) + total);

        String model = output.path("model").asText("");
        if (model.isBlank()) {
            model = "unknown";
        }
        BigDecimal cost = pricingService.estimate(model, prompt, completion);
        BigDecimal current = record.getCostUsd() == null ? BigDecimal.ZERO : record.getCostUsd();
        record.setCostUsd(current.add(cost).setScale(6, RoundingMode.HALF_UP));

        meterRegistry.counter("agentflow.llm.tokens", "model", model, "kind", "prompt").increment(prompt);
        meterRegistry.counter("agentflow.llm.tokens", "model", model, "kind", "completion").increment(completion);
    }

    private int firstInt(JsonNode node, String... keys) {
        for (String key : keys) {
            JsonNode value = node.path(key);
            if (value.isNumber()) {
                return value.asInt();
            }
        }
        return 0;
    }

    private int nvl(Integer value) {
        return value == null ? 0 : value;
    }

    private long elapsedSince(ExecutionRecord record) {
        if (record.getStartedAt() == null) {
            return record.getElapsedMs() == null ? 0 : record.getElapsedMs();
        }
        return Math.max(0, Duration.between(record.getStartedAt(), LocalDateTime.now()).toMillis());
    }

    private static final class RunningExecution {
        private final AtomicBoolean canceled = new AtomicBoolean(false);
        private volatile InputStream stream;

        private void checkCanceled() {
            if (canceled.get()) throw new CancellationException("已取消");
        }

        private synchronized void attach(InputStream input) throws IOException {
            stream = input;
            if (canceled.get()) {
                input.close();
                checkCanceled();
            }
        }

        private synchronized void cancel() {
            canceled.set(true);
            InputStream current = stream;
            if (current != null) {
                try {
                    current.close();
                } catch (IOException ignored) {
                    // 关闭上游流仅用于尽快释放连接
                }
            }
        }
    }

    /** 断点续跑的节点输出缓存：取上次成功节点（input 节点除外，保证新输入生效）。 */
    private JsonNode resumeCache(String resumeRunId, Long workflowId, CurrentUser user) {
        ExecutionRecord record = requireRecord(resumeRunId, user);
        if (!record.getWorkflowId().equals(workflowId)) {
            throw new BizException("续跑记录与当前工作流不一致");
        }
        List<ExecutionNodeLog> logs = nodeLogMapper.selectList(
                new LambdaQueryWrapper<ExecutionNodeLog>()
                        .eq(ExecutionNodeLog::getRunId, resumeRunId)
                        .eq(ExecutionNodeLog::getStatus, SUCCESS)
                        .orderByAsc(ExecutionNodeLog::getSeq));
        ObjectNode cache = objectMapper.createObjectNode();
        for (ExecutionNodeLog item : logs) {
            if ("input".equals(item.getNodeType())
                    || item.getOutputData() == null || item.getOutputData().isBlank()) {
                continue;
            }
            try {
                cache.set(item.getNodeId(), objectMapper.readTree(item.getOutputData()));
            } catch (Exception ex) {
                log.warn("skip corrupted node output, runId={} node={}: {}", resumeRunId, item.getNodeId(), ex.getMessage());
            }
        }
        return cache;
    }

    private String buildPayload(String runId, Long workflowId, JsonNode flow, ExecuteRequest request, CurrentUser user) {
        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("runId", runId);
        payload.put("workflowId", String.valueOf(workflowId));
        if (user != null && user.id() != null) {
            // 记忆节点按用户范围隔离时使用；子流程复用同一归属
            payload.put("userId", user.id());
        }
        payload.set("flow", flow);
        payload.set("input", objectMapper.valueToTree(request.getInput() == null ? Map.of() : request.getInput()));
        payload.set("providers", objectMapper.valueToTree(llmProviderService.credentialsForRun()));

        Map<String, JsonNode> subflows = collectSubflows(workflowId, flow, user);
        List<JsonNode> referencedFlows = new ArrayList<>(subflows.values());
        referencedFlows.add(flow);
        payload.set("mcpServers", objectMapper.valueToTree(mcpServerService.forRun(referencedFlows, user)));
        if (!subflows.isEmpty()) {
            payload.set("subflows", objectMapper.valueToTree(subflows));
        }
        if (request.getResumeRunId() != null && !request.getResumeRunId().isBlank()) {
            payload.set("resume", resumeCache(request.getResumeRunId().trim(), workflowId, user));
        }
        ObjectNode options = payload.putObject("options");
        int timeoutMs = request.getTimeoutMs() == null ? 120000 : request.getTimeoutMs();
        options.put("timeoutMs", Math.max(timeoutMs, approvalTimeoutMs(flow)));
        if (request.getMock() != null) {
            options.put("mock", request.getMock());
        }
        return payload.toString();
    }

    /** 人工审批节点会阻塞等待，执行级超时需要为最长的等待时间留出缓冲。 */
    private int approvalTimeoutMs(JsonNode flow) {
        int maxWaitSeconds = 0;
        JsonNode nodes = flow.path("nodes");
        if (nodes.isArray()) {
            for (JsonNode node : nodes) {
                if ("human_approval".equals(node.path("type").asText())) {
                    int wait = node.path("config").path("waitSeconds").asInt(120);
                    maxWaitSeconds = Math.max(maxWaitSeconds, Math.min(600, Math.max(0, wait)));
                }
            }
        }
        return maxWaitSeconds == 0 ? 0 : maxWaitSeconds * 1000 + 30_000;
    }

    /** 把 subflow / foreach 引用的工作流定义内联进 payload，Python 侧无需回查数据库。 */
    private Map<String, JsonNode> collectSubflows(Long parentWorkflowId, JsonNode flow, CurrentUser user) {
        Map<String, JsonNode> result = new LinkedHashMap<>();
        Set<Long> visiting = new HashSet<>();
        visiting.add(parentWorkflowId);
        collectSubflows(flow, result, visiting, 0, user);
        return result;
    }

    private void collectSubflows(JsonNode flow, Map<String, JsonNode> result,
                                 Set<Long> visiting, int depth, CurrentUser user) {
        if (depth > 4) {
            throw new BizException("子工作流嵌套层级过深（最多 5 层）");
        }
        JsonNode nodes = flow.path("nodes");
        if (!nodes.isArray()) {
            return;
        }
        for (JsonNode node : nodes) {
            String type = node.path("type").asText();
            JsonNode config = node.path("config");
            LinkedHashSet<Long> ids = new LinkedHashSet<>();
            if ("subflow".equals(type) || "foreach".equals(type)) {
                long id = "foreach".equals(type)
                        ? config.path("bodyWorkflowId").asLong(0)
                        : config.path("workflowId").asLong(0);
                if (id <= 0) {
                    id = config.path("workflowId").asLong(0);
                }
                if (id > 0) {
                    ids.add(id);
                }
            } else if ("orchestrator".equals(type)) {
                ids.addAll(orchestratorWorkerIds(config));
            }
            for (long id : ids) {
                if (!visiting.add(id)) {
                    throw new BizException("子工作流存在循环引用: " + id);
                }
                String key = String.valueOf(id);
                if (!result.containsKey(key)) {
                    if (result.size() >= 20) {
                        throw new BizException("单次执行最多引用 20 个子工作流");
                    }
                    JsonNode subFlow = workflowService.readFlow(workflowService.getEntity(id, user));
                    result.put(key, subFlow);
                    collectSubflows(subFlow, result, visiting, depth + 1, user);
                }
                visiting.remove(id);
            }
        }
    }

    private List<Long> orchestratorWorkerIds(JsonNode config) {
        JsonNode workers = config.path("workers");
        if (workers.isTextual()) {
            try {
                workers = objectMapper.readTree(workers.asText());
            } catch (Exception ex) {
                throw new BizException("协调节点执行者配置不是合法 JSON");
            }
        }
        LinkedHashSet<Long> ids = new LinkedHashSet<>();
        if (workers.isArray()) {
            for (JsonNode item : workers) {
                long id = item.path("workflowId").asLong(0);
                if (id > 0) {
                    ids.add(id);
                }
            }
        }
        return new ArrayList<>(ids);
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception ex) {
            return "null";
        }
    }

    /** Hide both missing records and records owned by another user behind the same 404. */
    private ExecutionRecord requireRecord(String runId, CurrentUser user) {
        ExecutionRecord record = recordMapper.selectOne(
                new LambdaQueryWrapper<ExecutionRecord>().eq(ExecutionRecord::getRunId, runId));
        if (record == null || (!"ADMIN".equals(user.role()) && !user.id().equals(record.getUserId()))) {
            throw BizException.notFound("执行记录不存在: " + runId);
        }
        return record;
    }
}
