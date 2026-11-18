package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.ApprovalCreateRequest;
import com.agentflow.dto.ApprovalDecisionRequest;
import com.agentflow.dto.ApprovalVO;
import com.agentflow.entity.ApprovalTask;
import com.agentflow.mapper.ApprovalTaskMapper;
import com.agentflow.security.CurrentUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 人工审批：节点创建任务后轮询状态，用户在「审批」页通过 / 驳回。
 *
 * <p>任务到期由读写时惰性标记为 EXPIRED，不依赖后台调度器；
 * 普通用户只能看到并处理自己的任务，管理员可以处理全部。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ApprovalService {

    private static final String PENDING = "PENDING";
    private static final String APPROVED = "APPROVED";
    private static final String REJECTED = "REJECTED";
    private static final String EXPIRED = "EXPIRED";
    private static final int MAX_CONTENT = 20_000;

    private final ApprovalTaskMapper taskMapper;

    public ApprovalVO create(ApprovalCreateRequest request) {
        String title = request.getTitle() == null ? "" : request.getTitle().trim();
        if (title.isEmpty()) {
            throw new BizException("审批标题不能为空");
        }
        String content = request.getContent() == null ? "" : request.getContent().trim();
        if (content.length() > MAX_CONTENT) {
            throw new BizException("审批内容不能超过 " + MAX_CONTENT + " 字");
        }
        int seconds = request.getExpiresInSeconds() == null ? 300 : request.getExpiresInSeconds();
        seconds = Math.max(30, Math.min(1800, seconds));

        ApprovalTask task = new ApprovalTask();
        task.setRunId(request.getRunId());
        task.setWorkflowId(request.getWorkflowId());
        task.setNodeId(request.getNodeId());
        task.setUserId(request.getUserId());
        task.setTitle(title);
        task.setContent(content);
        task.setStatus(PENDING);
        task.setExpiresAt(LocalDateTime.now().plusSeconds(seconds));
        taskMapper.insert(task);
        log.info("approval created, id={}, runId={}, node={}", task.getId(), task.getRunId(), task.getNodeId());
        return ApprovalVO.of(task);
    }

    public ApprovalVO get(Long id) {
        ApprovalTask task = require(id);
        expireIfNeeded(task);
        return ApprovalVO.of(task);
    }

    public List<ApprovalVO> list(CurrentUser user, String status) {
        LambdaQueryWrapper<ApprovalTask> wrapper = new LambdaQueryWrapper<>();
        if (user != null && !isAdmin(user)) {
            wrapper.eq(ApprovalTask::getUserId, user.id());
        }
        if (status != null && !status.isBlank()) {
            wrapper.eq(ApprovalTask::getStatus, status.trim().toUpperCase());
        }
        wrapper.orderByDesc(ApprovalTask::getId).last("LIMIT 200");
        List<ApprovalTask> tasks = taskMapper.selectList(wrapper);
        for (ApprovalTask task : tasks) {
            expireIfNeeded(task);
        }
        return tasks.stream().map(ApprovalVO::of).toList();
    }

    @Transactional
    public ApprovalVO decide(Long id, ApprovalDecisionRequest request, CurrentUser user) {
        ApprovalTask task = require(id);
        expireIfNeeded(task);
        if (!PENDING.equals(task.getStatus())) {
            throw new BizException("审批已处理或已过期: " + task.getStatus());
        }
        if (user == null || (!isAdmin(user) && (task.getUserId() == null || !task.getUserId().equals(user.id())))) {
            throw BizException.notFound("审批任务不存在: " + id);
        }
        task.setStatus(Boolean.TRUE.equals(request.getApproved()) ? APPROVED : REJECTED);
        String comment = request.getComment() == null ? "" : request.getComment().trim();
        task.setComment(comment.length() > 1000 ? comment.substring(0, 1000) : comment);
        task.setDecidedBy(user.id());
        task.setDecidedAt(LocalDateTime.now());
        taskMapper.updateById(task);
        log.info("approval decided, id={}, status={}, by={}", id, task.getStatus(), user.id());
        return ApprovalVO.of(task);
    }

    private ApprovalTask require(Long id) {
        ApprovalTask task = id == null ? null : taskMapper.selectById(id);
        if (task == null) {
            throw BizException.notFound("审批任务不存在: " + id);
        }
        return task;
    }

    private void expireIfNeeded(ApprovalTask task) {
        if (!PENDING.equals(task.getStatus())) {
            return;
        }
        if (task.getExpiresAt() != null && task.getExpiresAt().isBefore(LocalDateTime.now())) {
            task.setStatus(EXPIRED);
            task.setDecidedAt(LocalDateTime.now());
            taskMapper.updateById(task);
        }
    }

    private boolean isAdmin(CurrentUser user) {
        return user.role() != null && "ADMIN".equalsIgnoreCase(user.role());
    }
}
