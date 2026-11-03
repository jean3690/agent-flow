package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.common.PageResult;
import com.agentflow.dto.ExecuteRequest;
import com.agentflow.dto.ExecutionDetailVO;
import com.agentflow.dto.ExecutionSummaryVO;
import com.agentflow.dto.NodeLogVO;
import com.agentflow.entity.ExecutionNodeLog;
import com.agentflow.entity.ExecutionRecord;
import com.agentflow.entity.Workflow;
import com.agentflow.mapper.ExecutionNodeLogMapper;
import com.agentflow.mapper.ExecutionRecordMapper;
import com.agentflow.security.CurrentUser;
import com.agentflow.util.FlowValidator;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

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
    private final ExecutionRecordMapper recordMapper;
    private final ExecutionNodeLogMapper nodeLogMapper;
    private final ObjectMapper objectMapper;
    private final ThreadPoolTaskExecutor executor;

    public ExecutionService(
            AiClient aiClient,
            WorkflowService workflowService,
            LlmProviderService llmProviderService,
            ExecutionRecordMapper recordMapper,
            ExecutionNodeLogMapper nodeLogMapper,
            ObjectMapper objectMapper,
            @Qualifier("executionExecutor") ThreadPoolTaskExecutor executor) {
        this.aiClient = aiClient;
        this.workflowService = workflowService;
        this.llmProviderService = llmProviderService;
        this.recordMapper = recordMapper;
        this.nodeLogMapper = nodeLogMapper;
        this.objectMapper = objectMapper;
        this.executor = executor;
    }

    public SseEmitter execute(Long workflowId, ExecuteRequest request, CurrentUser user) {
        Workflow workflow = workflowService.getEntity(workflowId, user);
        JsonNode flow = workflowService.readFlow(workflow);
        FlowValidator.validate(flow);

        String runId = UUID.randomUUID().toString().replace("-", "");
        ExecutionRecord record = new ExecutionRecord();
        record.setRunId(runId);
        record.setWorkflowId(workflowId);
        record.setWorkflowName(workflow.getName());
        record.setUserId(user.id());
        record.setStatus(RUNNING);
        record.setNodeCount(FlowValidator.countNodes(flow));
        record.setElapsedMs(0L);
        record.setStartedAt(LocalDateTime.now());
        record.setInputData(writeJson(request.getInput() == null ? Map.of() : request.getInput()));
        recordMapper.insert(record);

        String payload = buildPayload(runId, workflowId, flow, request);
        SseEmitter emitter = new SseEmitter(0L);
        Map<String, ExecutionNodeLog> logs = new ConcurrentHashMap<>();
        AtomicBoolean closed = new AtomicBoolean(false);
        emitter.onCompletion(() -> closed.set(true));
        emitter.onTimeout(() -> closed.set(true));
        emitter.onError(error -> closed.set(true));

        RunningExecution execution = new RunningExecution();
        running.put(runId, execution);
        executor.execute(() -> stream(emitter, record, payload, logs, closed, execution));
        return emitter;
    }

    /** 取消执行：通知 ai-service 终止 LangGraph 任务并断开上游流。 */
    public void cancel(String runId) {
        ExecutionRecord record = recordMapper.selectOne(
                new LambdaQueryWrapper<ExecutionRecord>().eq(ExecutionRecord::getRunId, runId));
        if (record == null) {
            throw BizException.notFound("执行记录不存在: " + runId);
        }
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
        execution.canceled.set(true);
        try {
            aiClient.postJson("/v1/executions/" + runId + "/cancel", Map.of());
        } catch (Exception ex) {
            log.debug("cancel request to ai-service failed, runId={}: {}", runId, ex.getMessage());
        }
        execution.close();
    }

    @Transactional
    public void delete(String runId) {
        ExecutionRecord record = recordMapper.selectOne(
                new LambdaQueryWrapper<ExecutionRecord>().eq(ExecutionRecord::getRunId, runId));
        if (record == null) {
            throw BizException.notFound("执行记录不存在: " + runId);
        }
        nodeLogMapper.delete(new LambdaQueryWrapper<ExecutionNodeLog>()
                .eq(ExecutionNodeLog::getRunId, runId));
        recordMapper.deleteById(record.getId());
    }

    public PageResult<ExecutionSummaryVO> page(long page, long size, Long workflowId, String status) {
        LambdaQueryWrapper<ExecutionRecord> query = new LambdaQueryWrapper<ExecutionRecord>()
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
                        .elapsedMs(item.getElapsedMs())
                        .errorMessage(item.getErrorMessage())
                        .startedAt(item.getStartedAt())
                        .finishedAt(item.getFinishedAt())
                        .build())
                .toList();
        return new PageResult<>(records, result.getTotal(), page, size);
    }

    public ExecutionDetailVO detail(String runId) {
        ExecutionRecord record = recordMapper.selectOne(
                new LambdaQueryWrapper<ExecutionRecord>().eq(ExecutionRecord::getRunId, runId));
        if (record == null) {
            throw BizException.notFound("执行记录不存在: " + runId);
        }
        List<ExecutionNodeLog> logs = nodeLogMapper.selectList(
                new LambdaQueryWrapper<ExecutionNodeLog>()
                        .eq(ExecutionNodeLog::getRunId, runId)
                        .orderByAsc(ExecutionNodeLog::getSeq));
        return ExecutionDetailVO.builder()
                .runId(record.getRunId())
                .workflowId(record.getWorkflowId())
                .workflowName(record.getWorkflowName())
                .status(record.getStatus())
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
        String event = null;
        StringBuilder data = new StringBuilder();
        try (InputStream input = aiClient.openExecution(payload);
             BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
            execution.stream = input;
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isEmpty()) {
                    if (event != null) {
                        String body = data.toString();
                        if (!closed.get()) {
                            try {
                                emitter.send(SseEmitter.event().name(event).data(body, MediaType.APPLICATION_JSON));
                            } catch (Exception sendError) {
                                closed.set(true);
                                log.info("client disconnected from run {}", record.getRunId());
                            }
                        }
                        handleEvent(record, logs, event, body);
                    }
                    event = null;
                    data.setLength(0);
                } else if (line.startsWith("event:")) {
                    event = line.substring(6).trim();
                } else if (line.startsWith("data:")) {
                    data.append(line.substring(5).trim());
                }
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
                    }
                }
                case "node_failed" -> {
                    ExecutionNodeLog log = logs.get(node.path("nodeId").asText());
                    if (log != null) {
                        log.setStatus(FAILED);
                        log.setErrorMessage(node.path("error").path("message").asText("执行失败"));
                        log.setElapsedMs(node.path("elapsedMs").asLong());
                        log.setFinishedAt(LocalDateTime.now());
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
            List<ExecutionNodeLog> ordered = new ArrayList<>(logs.values());
            ordered.sort(Comparator.comparing(item -> item.getSeq() == null ? 0 : item.getSeq()));
            for (ExecutionNodeLog log : ordered) {
                nodeLogMapper.insert(log);
            }
            if (record.getStatus().equals(RUNNING)) {
                if (execution.canceled.get()) {
                    record.setStatus(CANCELED);
                    record.setErrorMessage("已取消");
                    record.setElapsedMs(elapsedSince(record));
                } else {
                    record.setStatus(FAILED);
                    record.setErrorMessage("执行中断");
                }
                record.setFinishedAt(LocalDateTime.now());
            }
            recordMapper.updateById(record);
        } catch (Exception ex) {
            log.error("failed to persist execution {}, runId={}", record.getId(), record.getRunId(), ex);
        }
    }

    private long elapsedSince(ExecutionRecord record) {
        if (record.getStartedAt() == null) {
            return record.getElapsedMs() == null ? 0 : record.getElapsedMs();
        }
        return Math.max(0, Duration.between(record.getStartedAt(), LocalDateTime.now()).toMillis());
    }

    private static final class RunningExecution {        private final AtomicBoolean canceled = new AtomicBoolean(false);
        private volatile InputStream stream;

        private void close() {
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
    private JsonNode resumeCache(String resumeRunId, Long workflowId) {
        ExecutionRecord record = recordMapper.selectOne(
                new LambdaQueryWrapper<ExecutionRecord>().eq(ExecutionRecord::getRunId, resumeRunId));
        if (record == null) {
            throw BizException.notFound("要续跑的执行记录不存在: " + resumeRunId);
        }
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

    private String buildPayload(String runId, Long workflowId, JsonNode flow, ExecuteRequest request) {
        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("runId", runId);
        payload.put("workflowId", String.valueOf(workflowId));
        payload.set("flow", flow);
        payload.set("input", objectMapper.valueToTree(request.getInput() == null ? Map.of() : request.getInput()));
        payload.set("providers", objectMapper.valueToTree(llmProviderService.credentialsForRun()));
        if (request.getResumeRunId() != null && !request.getResumeRunId().isBlank()) {
            payload.set("resume", resumeCache(request.getResumeRunId().trim(), workflowId));
        }
        ObjectNode options = payload.putObject("options");
        options.put("timeoutMs", request.getTimeoutMs() == null ? 120000 : request.getTimeoutMs());
        if (request.getMock() != null) {
            options.put("mock", request.getMock());
        }
        return payload.toString();
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception ex) {
            return "null";
        }
    }
}
