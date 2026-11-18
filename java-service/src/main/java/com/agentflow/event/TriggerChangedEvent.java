package com.agentflow.event;

/** 触发器创建/更新/删除后发布，调度器据此刷新内存中的定时任务。 */
public record TriggerChangedEvent(Long triggerId) {
}
