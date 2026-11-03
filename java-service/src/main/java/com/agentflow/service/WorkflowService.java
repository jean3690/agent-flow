package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.common.PageResult;
import com.agentflow.dto.WorkflowDetailVO;
import com.agentflow.dto.WorkflowSaveRequest;
import com.agentflow.dto.WorkflowSummaryVO;
import com.agentflow.entity.Workflow;
import com.agentflow.mapper.WorkflowMapper;
import com.agentflow.security.CurrentUser;
import com.agentflow.util.FlowValidator;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@RequiredArgsConstructor
public class WorkflowService {

    private final WorkflowMapper workflowMapper;
    private final ObjectMapper objectMapper;

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
        if (request.getStatus() != null) {
            workflow.setStatus(request.getStatus());
        }
        workflow.setVersion(workflow.getVersion() == null ? 1 : workflow.getVersion() + 1);
        workflowMapper.updateById(workflow);
        return toDetail(workflow);
    }

    @Transactional
    public void delete(Long id, CurrentUser user) {
        Workflow workflow = getEntity(id, user);
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
        return toDetail(copy);
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
