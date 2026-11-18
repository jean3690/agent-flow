package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.ExecuteRequest;
import com.agentflow.dto.TriggerRequest;
import com.agentflow.dto.TriggerVO;
import com.agentflow.dto.WebhookResultVO;
import com.agentflow.entity.Workflow;
import com.agentflow.event.TriggerChangedEvent;
import com.agentflow.entity.WorkflowTrigger;
import com.agentflow.mapper.WorkflowMapper;
import com.agentflow.mapper.WorkflowTriggerMapper;
import com.agentflow.security.CurrentUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.scheduling.support.CronExpression;
import org.springframework.stereotype.Service;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

@Slf4j
@Service
@RequiredArgsConstructor
public class TriggerService {

    private static final String TYPE_CRON = "CRON";
    private static final String TYPE_WEBHOOK = "WEBHOOK";
    private static final String DEFAULT_TIMEZONE = "Asia/Shanghai";
    private static final SecureRandom RANDOM = new SecureRandom();

    private final WorkflowTriggerMapper triggerMapper;
    private final WorkflowMapper workflowMapper;
    private final ExecutionService executionService;
    private final ObjectMapper objectMapper;
    private final ApplicationEventPublisher events;

    /** 防止同一个 CRON 触发器在上一次还没跑完时重复堆积。 */
    private final Set<Long> firing = ConcurrentHashMap.newKeySet();

    public List<TriggerVO> list(Long workflowId, CurrentUser user) {
        requireWorkflow(workflowId, user);
        return triggerMapper.selectList(new LambdaQueryWrapper<WorkflowTrigger>()
                        .eq(WorkflowTrigger::getWorkflowId, workflowId)
                        .orderByDesc(WorkflowTrigger::getId))
                .stream().map(this::toVO).toList();
    }

    public TriggerVO create(Long workflowId, TriggerRequest request, CurrentUser user) {
        Workflow workflow = requireWorkflow(workflowId, user);
        String type = normalizeType(request.getType());
        String cron = type.equals(TYPE_CRON) ? validateCron(request.getCronExpression()) : null;
        String timezone = normalizeTimezone(request.getTimezone());

        WorkflowTrigger trigger = new WorkflowTrigger();
        trigger.setWorkflowId(workflowId);
        trigger.setUserId(workflow.getUserId());
        trigger.setName(request.getName().trim());
        trigger.setType(type);
        trigger.setEnabled(request.getEnabled() == null || request.getEnabled() ? 1 : 0);
        trigger.setCronExpression(cron);
        trigger.setTimezone(timezone);
        trigger.setWebhookToken(type.equals(TYPE_WEBHOOK) ? newToken() : null);
        trigger.setInputData(writeInput(request.getInput()));
        trigger.setNextRunAt(cron == null ? null : nextRun(cron, timezone));
        triggerMapper.insert(trigger);
        events.publishEvent(new TriggerChangedEvent(trigger.getId()));
        return toVO(trigger);
    }

    public TriggerVO update(Long id, TriggerRequest request, CurrentUser user) {
        WorkflowTrigger trigger = requireTrigger(id, user);
        String type = normalizeType(request.getType());
        String cron = type.equals(TYPE_CRON) ? validateCron(request.getCronExpression()) : null;
        String timezone = normalizeTimezone(request.getTimezone());

        trigger.setName(request.getName().trim());
        trigger.setType(type);
        trigger.setEnabled(request.getEnabled() == null || request.getEnabled() ? 1 : 0);
        trigger.setCronExpression(cron);
        trigger.setTimezone(timezone);
        trigger.setInputData(writeInput(request.getInput()));
        trigger.setNextRunAt(cron == null ? null : nextRun(cron, timezone));
        if (type.equals(TYPE_WEBHOOK)) {
            if (trigger.getWebhookToken() == null || trigger.getWebhookToken().isBlank()) {
                trigger.setWebhookToken(newToken());
            }
        } else {
            trigger.setWebhookToken(null);
        }
        triggerMapper.updateById(trigger);
        events.publishEvent(new TriggerChangedEvent(trigger.getId()));
        return toVO(trigger);
    }

    public void delete(Long id, CurrentUser user) {
        WorkflowTrigger trigger = requireTrigger(id, user);
        triggerMapper.deleteById(trigger.getId());
        events.publishEvent(new TriggerChangedEvent(trigger.getId()));
    }

    public TriggerVO rotateToken(Long id, CurrentUser user) {
        WorkflowTrigger trigger = requireTrigger(id, user);
        if (!TYPE_WEBHOOK.equals(trigger.getType())) {
            throw new BizException("只有 Webhook 触发器才有令牌");
        }
        trigger.setWebhookToken(newToken());
        triggerMapper.updateById(trigger);
        return toVO(trigger);
    }

    public TriggerVO runNow(Long id, CurrentUser user) {
        WorkflowTrigger trigger = requireTrigger(id, user);
        fire(trigger, false, false);
        return toVO(triggerMapper.selectById(id));
    }

    public WebhookResultVO webhook(String token, JsonNode body) {
        WorkflowTrigger trigger = triggerMapper.selectOne(new LambdaQueryWrapper<WorkflowTrigger>()
                .eq(WorkflowTrigger::getWebhookToken, token.trim())
                .eq(WorkflowTrigger::getEnabled, 1));
        if (trigger == null || !TYPE_WEBHOOK.equals(trigger.getType())) {
            throw BizException.notFound("Webhook 不存在或已停用");
        }
        Map<String, Object> input = parseInput(trigger.getInputData());
        mergeBody(input, body);
        ExecuteRequest request = new ExecuteRequest();
        request.setInput(input);
        updateLastRun(trigger.getId(), null, "RUNNING");
        String runId = executionService.submit(trigger.getWorkflowId(), request, trigger.getUserId(), true,
                result -> updateLastRun(trigger.getId(), result.getRunId(), result.getStatus()));
        events.publishEvent(new TriggerChangedEvent(trigger.getId()));
        return WebhookResultVO.builder()
                .triggerId(trigger.getId())
                .runId(runId)
                .status("ACCEPTED")
                .build();
    }

    /** 由调度器调用；已停用、已删除或非 CRON 时静默返回。 */
    public void fireCron(Long triggerId) {
        WorkflowTrigger trigger = triggerMapper.selectById(triggerId);
        if (trigger == null || trigger.getEnabled() == null || trigger.getEnabled() != 1
                || !TYPE_CRON.equals(trigger.getType())) {
            return;
        }
        try {
            fire(trigger, true, true);
        } catch (Exception ex) {
            log.error("trigger {} fire failed: {}", triggerId, ex.getMessage());
            updateLastRun(triggerId, null, "FAILED");
        }
    }

    /** 提交一次异步执行；guard 为 true 时同一触发器串行执行。 */
    private String fire(WorkflowTrigger trigger, boolean guard, boolean checkEnabled) {
        if (checkEnabled && (trigger.getEnabled() == null || trigger.getEnabled() != 1)) {
            throw new BizException("触发器已停用");
        }
        if (guard && !firing.add(trigger.getId())) {
            throw new BizException("上一次执行尚未结束");
        }
        Workflow workflow = workflowMapper.selectById(trigger.getWorkflowId());
        if (workflow == null) {
            firing.remove(trigger.getId());
            throw BizException.notFound("工作流不存在: " + trigger.getWorkflowId());
        }
        ExecuteRequest request = new ExecuteRequest();
        request.setInput(parseInput(trigger.getInputData()));
        updateLastRun(trigger.getId(), null, "RUNNING");
        try {
            return executionService.submit(trigger.getWorkflowId(), request, trigger.getUserId(), true, result -> {
                if (guard) {
                    firing.remove(trigger.getId());
                }
                updateLastRun(trigger.getId(), result.getRunId(), result.getStatus());
            });
        } catch (RuntimeException ex) {
            if (guard) {
                firing.remove(trigger.getId());
            }
            throw ex;
        }
    }

    public List<WorkflowTrigger> enabledCronTriggers() {
        return triggerMapper.selectList(new LambdaQueryWrapper<WorkflowTrigger>()
                .eq(WorkflowTrigger::getEnabled, 1)
                .eq(WorkflowTrigger::getType, TYPE_CRON)
                .isNotNull(WorkflowTrigger::getCronExpression));
    }

    public WorkflowTrigger find(Long id) {
        return triggerMapper.selectById(id);
    }

    public void refreshNextRun(Long triggerId) {
        WorkflowTrigger trigger = triggerMapper.selectById(triggerId);
        if (trigger == null || !TYPE_CRON.equals(trigger.getType()) || trigger.getCronExpression() == null) {
            return;
        }
        trigger.setNextRunAt(nextRun(trigger.getCronExpression(), trigger.getTimezone()));
        triggerMapper.updateById(trigger);
    }

    public void markScheduleError(Long triggerId, String message) {
        log.warn("trigger {} schedule error: {}", triggerId, message);
    }

    private void updateLastRun(Long triggerId, String runId, String status) {
        WorkflowTrigger trigger = triggerMapper.selectById(triggerId);
        if (trigger == null) {
            return;
        }
        trigger.setLastRunId(runId);
        trigger.setLastStatus(status);
        trigger.setLastRunAt(LocalDateTime.now());
        if (TYPE_CRON.equals(trigger.getType()) && trigger.getCronExpression() != null) {
            trigger.setNextRunAt(nextRun(trigger.getCronExpression(), trigger.getTimezone()));
        }
        triggerMapper.updateById(trigger);
    }

    private void mergeBody(Map<String, Object> input, JsonNode body) {
        if (body == null || body.isNull()) {
            return;
        }
        if (body.isObject()) {
            body.fields().forEachRemaining(entry ->
                    input.put(entry.getKey(), objectMapper.convertValue(entry.getValue(), Object.class)));
        } else {
            input.put("body", objectMapper.convertValue(body, Object.class));
        }
    }

    private String writeInput(Map<String, Object> input) {
        try {
            return objectMapper.writeValueAsString(input == null ? Map.of() : input);
        } catch (Exception ex) {
            throw new BizException("触发器输入序列化失败");
        }
    }

    private Map<String, Object> parseInput(String json) {
        if (json == null || json.isBlank()) {
            return new LinkedHashMap<>();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<LinkedHashMap<String, Object>>() {
            });
        } catch (Exception ex) {
            return new LinkedHashMap<>();
        }
    }

    private TriggerVO toVO(WorkflowTrigger trigger) {
        return TriggerVO.builder()
                .id(trigger.getId())
                .workflowId(trigger.getWorkflowId())
                .name(trigger.getName())
                .type(trigger.getType())
                .enabled(trigger.getEnabled() != null && trigger.getEnabled() == 1)
                .cronExpression(trigger.getCronExpression())
                .timezone(trigger.getTimezone())
                .webhookPath(TYPE_WEBHOOK.equals(trigger.getType()) && trigger.getWebhookToken() != null
                        ? "/api/triggers/webhook/" + trigger.getWebhookToken()
                        : null)
                .input(parseInput(trigger.getInputData()))
                .lastRunId(trigger.getLastRunId())
                .lastStatus(trigger.getLastStatus())
                .lastRunAt(trigger.getLastRunAt())
                .nextRunAt(trigger.getNextRunAt())
                .createdAt(trigger.getCreatedAt())
                .updatedAt(trigger.getUpdatedAt())
                .build();
    }

    private Workflow requireWorkflow(Long workflowId, CurrentUser user) {
        Workflow workflow = workflowMapper.selectById(workflowId);
        if (workflow == null) {
            throw BizException.notFound("工作流不存在: " + workflowId);
        }
        if (user != null && workflow.getUserId() != null
                && !workflow.getUserId().equals(user.id()) && !"ADMIN".equals(user.role())) {
            throw BizException.notFound("工作流不存在: " + workflowId);
        }
        return workflow;
    }

    private WorkflowTrigger requireTrigger(Long id, CurrentUser user) {
        WorkflowTrigger trigger = triggerMapper.selectById(id);
        if (trigger == null) {
            throw BizException.notFound("触发器不存在: " + id);
        }
        requireWorkflow(trigger.getWorkflowId(), user);
        return trigger;
    }

    private String normalizeType(String type) {
        String value = type == null ? "" : type.trim().toUpperCase();
        if (!TYPE_CRON.equals(value) && !TYPE_WEBHOOK.equals(value)) {
            throw new BizException("触发类型仅支持 CRON 或 WEBHOOK");
        }
        return value;
    }

    /** 兼容 5 段（分 时 日 月 周）写法，内部统一补成 Spring 的 6 段。 */
    public static String validateCron(String expression) {
        String value = expression == null ? "" : expression.trim().replaceAll("\\s+", " ");
        if (value.isEmpty()) {
            throw new BizException("CRON 表达式不能为空");
        }
        int fields = value.split(" ").length;
        if (fields == 5) {
            value = "0 " + value;
        } else if (fields != 6) {
            throw new BizException("CRON 表达式需为 5 段或 6 段");
        }
        try {
            CronExpression.parse(value);
        } catch (IllegalArgumentException ex) {
            throw new BizException("CRON 表达式不合法: " + ex.getMessage());
        }
        return value;
    }

    private String normalizeTimezone(String timezone) {
        String value = timezone == null || timezone.isBlank() ? DEFAULT_TIMEZONE : timezone.trim();
        try {
            ZoneId.of(value);
        } catch (Exception ex) {
            throw new BizException("时区不合法: " + value);
        }
        return value;
    }

    private LocalDateTime nextRun(String cron, String timezone) {
        return CronExpression.parse(cron).next(LocalDateTime.now(ZoneId.of(timezone)));
    }

    private String newToken() {
        byte[] bytes = new byte[24];
        RANDOM.nextBytes(bytes);
        return "wh_" + Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
