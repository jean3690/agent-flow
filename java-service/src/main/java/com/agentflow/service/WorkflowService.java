package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.common.PageResult;
import com.agentflow.dto.WorkflowDetailVO;
import com.agentflow.dto.WorkflowSaveRequest;
import com.agentflow.dto.WorkflowSummaryVO;
import com.agentflow.dto.WorkflowVersionVO;
import com.agentflow.entity.Workflow;
import com.agentflow.entity.WorkflowTrigger;
import com.agentflow.entity.WorkflowVersion;
import com.agentflow.event.TriggerChangedEvent;
import com.agentflow.mapper.WorkflowMapper;
import com.agentflow.mapper.WorkflowTriggerMapper;
import com.agentflow.mapper.WorkflowVersionMapper;
import com.agentflow.security.CurrentUser;
import com.agentflow.util.FlowValidator;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
public class WorkflowService {

    private final WorkflowMapper workflowMapper;
    private final WorkflowTriggerMapper triggerMapper;
    private final WorkflowVersionMapper versionMapper;
    private final ApplicationEventPublisher events;
    private final ObjectMapper objectMapper;

    /** 执行时实际使用的 flow 与版本号。 */
    public record FlowSelection(JsonNode flow, Integer version, boolean published) {
    }

    public PageResult<WorkflowSummaryVO> page(long page, long size, String keyword, CurrentUser user) {
        LambdaQueryWrapper<Workflow> query = new LambdaQueryWrapper<Workflow>()
                .eq(user != null, Workflow::getUserId, user == null ? null : user.id())
                .like(keyword != null && !keyword.isBlank(), Workflow::getName, keyword)
                .orderByDesc(Workflow::getUpdatedAt);
        Page<Workflow> result = workflowMapper.selectPage(new Page<>(page, size), query);
        List<WorkflowSummaryVO> records = result.getRecords().stream().map(this::toSummary).toList();
        return new PageResult<>(records, result.getTotal(), page, size);
    }

    public WorkflowDetailVO detail(Long id, CurrentUser user) {
        return toDetail(getEntity(id, user));
    }

    @Transactional
    public WorkflowDetailVO create(WorkflowSaveRequest request, CurrentUser user) {
        FlowValidator.validateStructure(request.getFlow());
        Workflow workflow = new Workflow();
        workflow.setName(request.getName());
        workflow.setDescription(request.getDescription());
        workflow.setEngineType(request.getEngineType() == null ? "langgraph" : request.getEngineType());
        workflow.setFlowData(writeFlow(request.getFlow()));
        workflow.setStatus(request.getStatus() == null ? 1 : request.getStatus());
        workflow.setVersion(1);
        workflow.setUserId(user.id());
        workflowMapper.insert(workflow);
        saveSnapshot(workflow, "初始版本", user.id());
        return toDetail(workflow);
    }

    @Transactional
    public WorkflowDetailVO update(Long id, WorkflowSaveRequest request, CurrentUser user) {
        FlowValidator.validateStructure(request.getFlow());
        Workflow workflow = getEntity(id, user);
        workflow.setName(request.getName());
        workflow.setDescription(request.getDescription());
        if (request.getEngineType() != null) {
            workflow.setEngineType(request.getEngineType());
        }
        workflow.setFlowData(writeFlow(request.getFlow()));
        // 已发布的工作流保存草稿时仍保持"已发布"状态，发布版本指针不变
        if (workflow.getPublishedVersion() != null) {
            workflow.setStatus(2);
        } else if (request.getStatus() != null) {
            workflow.setStatus(request.getStatus());
        }
        workflow.setVersion(workflow.getVersion() == null ? 1 : workflow.getVersion() + 1);
        workflowMapper.updateById(workflow);
        saveSnapshot(workflow, "保存 v" + workflow.getVersion(), user.id());
        return toDetail(workflow);
    }

    @Transactional
    public void delete(Long id, CurrentUser user) {
        Workflow workflow = getEntity(id, user);
        List<WorkflowTrigger> triggers = triggerMapper.selectList(
                new LambdaQueryWrapper<WorkflowTrigger>()
                        .eq(WorkflowTrigger::getWorkflowId, workflow.getId()));
        for (WorkflowTrigger trigger : triggers) {
            triggerMapper.deleteById(trigger.getId());
            events.publishEvent(new TriggerChangedEvent(trigger.getId()));
        }
        versionMapper.delete(new LambdaQueryWrapper<WorkflowVersion>()
                .eq(WorkflowVersion::getWorkflowId, workflow.getId()));
        workflowMapper.deleteById(workflow.getId());
    }

    @Transactional
    public WorkflowDetailVO duplicate(Long id, CurrentUser user) {
        Workflow source = getEntity(id, user);
        Workflow copy = new Workflow();
        copy.setName(source.getName() + " 副本");
        copy.setDescription(source.getDescription());
        copy.setEngineType(source.getEngineType());
        copy.setFlowData(source.getFlowData());
        copy.setStatus(1);
        copy.setVersion(1);
        copy.setUserId(user.id());
        workflowMapper.insert(copy);
        saveSnapshot(copy, "复制自工作流 #" + source.getId(), user.id());
        return toDetail(copy);
    }

    public List<WorkflowVersionVO> listVersions(Long id, CurrentUser user) {
        Workflow workflow = getEntity(id, user);
        return versionMapper.selectList(new LambdaQueryWrapper<WorkflowVersion>()
                        .eq(WorkflowVersion::getWorkflowId, id)
                        .orderByDesc(WorkflowVersion::getVersion))
                .stream()
                .map(version -> toVersionVO(version, workflow, false))
                .toList();
    }

    public WorkflowVersionVO versionDetail(Long id, Integer version, CurrentUser user) {
        Workflow workflow = getEntity(id, user);
        WorkflowVersion snapshot = findVersion(id, version);
        if (snapshot == null) {
            throw BizException.notFound("版本不存在: v" + version);
        }
        return toVersionVO(snapshot, workflow, true);
    }

    /** 把历史版本内容复制回工作流，并生成一个新版本（不删除历史）。 */
    @Transactional
    public WorkflowDetailVO rollback(Long id, Integer version, CurrentUser user) {
        Workflow workflow = getEntity(id, user);
        WorkflowVersion target = findVersion(id, version);
        if (target == null) {
            throw BizException.notFound("版本不存在: v" + version);
        }
        workflow.setFlowData(target.getFlowData());
        workflow.setEngineType(target.getEngineType());
        workflow.setVersion(workflow.getVersion() == null ? 1 : workflow.getVersion() + 1);
        workflowMapper.updateById(workflow);
        saveSnapshot(workflow, "回滚自 v" + version, user.id());
        return toDetail(workflow);
    }

    /** 发布当前版本；触发器与 Webhook 将固定执行该版本。 */
    public WorkflowDetailVO publish(Long id, CurrentUser user) {
        Workflow workflow = getEntity(id, user);
        ensureSnapshot(workflow, "发布前快照", user.id());
        workflow.setPublishedVersion(workflow.getVersion());
        workflow.setPublishedAt(LocalDateTime.now());
        workflow.setStatus(2);
        workflowMapper.updateById(workflow);
        return toDetail(workflow);
    }

    public WorkflowDetailVO unpublish(Long id, CurrentUser user) {
        Workflow workflow = getEntity(id, user);
        workflow.setPublishedVersion(null);
        workflow.setPublishedAt(null);
        workflow.setStatus(1);
        workflowMapper.updateById(workflow);
        return toDetail(workflow);
    }

    /**
     * 选择执行用 flow：preferPublished=true 时优先取发布版本快照（触发器/Webhook），
     * 未发布或快照缺失时回退到当前草稿。
     */
    public FlowSelection flowForRun(Workflow workflow, boolean preferPublished) {
        if (preferPublished && workflow.getPublishedVersion() != null) {
            WorkflowVersion snapshot = findVersion(workflow.getId(), workflow.getPublishedVersion());
            if (snapshot != null) {
                return new FlowSelection(readFlow(snapshot.getFlowData()), snapshot.getVersion(), true);
            }
        }
        return new FlowSelection(readFlow(workflow), workflow.getVersion(), false);
    }

    private WorkflowVersion findVersion(Long workflowId, Integer version) {
        if (version == null) {
            return null;
        }
        return versionMapper.selectOne(new LambdaQueryWrapper<WorkflowVersion>()
                .eq(WorkflowVersion::getWorkflowId, workflowId)
                .eq(WorkflowVersion::getVersion, version));
    }

    private void ensureSnapshot(Workflow workflow, String note, Long userId) {
        if (findVersion(workflow.getId(), workflow.getVersion()) == null) {
            saveSnapshot(workflow, note, userId);
        }
    }

    private void saveSnapshot(Workflow workflow, String note, Long userId) {
        WorkflowVersion snapshot = new WorkflowVersion();
        snapshot.setWorkflowId(workflow.getId());
        snapshot.setVersion(workflow.getVersion() == null ? 1 : workflow.getVersion());
        snapshot.setName(workflow.getName());
        snapshot.setDescription(workflow.getDescription());
        snapshot.setEngineType(workflow.getEngineType());
        snapshot.setFlowData(workflow.getFlowData());
        snapshot.setNote(note);
        snapshot.setCreatedBy(userId);
        versionMapper.insert(snapshot);
    }

    private WorkflowVersionVO toVersionVO(WorkflowVersion version, Workflow workflow, boolean withFlow) {
        return WorkflowVersionVO.builder()
                .id(version.getId())
                .workflowId(version.getWorkflowId())
                .version(version.getVersion())
                .name(version.getName())
                .description(version.getDescription())
                .engineType(version.getEngineType())
                .note(version.getNote())
                .createdBy(version.getCreatedBy())
                .createdAt(version.getCreatedAt())
                .published(version.getVersion().equals(workflow.getPublishedVersion()))
                .current(version.getVersion().equals(workflow.getVersion()))
                .flow(withFlow ? readFlow(version.getFlowData()) : null)
                .build();
    }

    public Workflow getEntity(Long id) {
        Workflow workflow = workflowMapper.selectById(id);
        if (workflow == null) {
            throw BizException.notFound("工作流不存在: " + id);
        }
        return workflow;
    }

    /** 归属校验：非本人且非管理员一律按不存在处理，避免暴露其他用户的工作流。 */
    public Workflow getEntity(Long id, CurrentUser user) {
        Workflow workflow = getEntity(id);
        if (user != null && workflow.getUserId() != null
                && !workflow.getUserId().equals(user.id()) && !"ADMIN".equals(user.role())) {
            throw BizException.notFound("工作流不存在: " + id);
        }
        return workflow;
    }

    public JsonNode readFlow(Workflow workflow) {
        return readFlow(workflow.getFlowData());
    }

    /** 供子工作流节点读取被引用工作流的定义（不做归属校验，执行前由调用方决定权限）。 */
    public JsonNode readFlowById(Long id) {
        return readFlow(getEntity(id));
    }

    public JsonNode readFlow(String flowData) {
        if (flowData == null || flowData.isBlank()) {
            ObjectNode empty = objectMapper.createObjectNode();
            empty.putArray("nodes");
            empty.putArray("edges");
            return empty;
        }
        try {
            return objectMapper.readTree(flowData);
        } catch (JsonProcessingException ex) {
            throw new BizException("工作流定义不是合法 JSON");
        }
    }

    public WorkflowSummaryVO toSummary(Workflow workflow) {
        JsonNode flow = safeFlow(workflow.getFlowData());
        return WorkflowSummaryVO.builder()
                .id(workflow.getId())
                .name(workflow.getName())
                .description(workflow.getDescription())
                .engineType(workflow.getEngineType())
                .status(workflow.getStatus())
                .version(workflow.getVersion())
                .publishedVersion(workflow.getPublishedVersion())
                .nodeCount(FlowValidator.countNodes(flow))
                .createdAt(workflow.getCreatedAt())
                .updatedAt(workflow.getUpdatedAt())
                .build();
    }

    public WorkflowDetailVO toDetail(Workflow workflow) {
        return WorkflowDetailVO.builder()
                .id(workflow.getId())
                .name(workflow.getName())
                .description(workflow.getDescription())
                .engineType(workflow.getEngineType())
                .status(workflow.getStatus())
                .version(workflow.getVersion())
                .publishedVersion(workflow.getPublishedVersion())
                .publishedAt(workflow.getPublishedAt())
                .flow(safeFlow(workflow.getFlowData()))
                .createdAt(workflow.getCreatedAt())
                .updatedAt(workflow.getUpdatedAt())
                .build();
    }

    private JsonNode safeFlow(String flowData) {
        if (flowData == null || flowData.isBlank()) {
            ObjectNode empty = objectMapper.createObjectNode();
            empty.putArray("nodes");
            empty.putArray("edges");
            return empty;
        }
        try {
            return objectMapper.readTree(flowData);
        } catch (JsonProcessingException ex) {
            ObjectNode empty = objectMapper.createObjectNode();
            empty.putArray("nodes");
            empty.putArray("edges");
            return empty;
        }
    }

    private String writeFlow(JsonNode flow) {
        try {
            return objectMapper.writeValueAsString(flow);
        } catch (JsonProcessingException ex) {
            throw new BizException("工作流定义序列化失败");
        }
    }
}
