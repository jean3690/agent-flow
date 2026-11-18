package com.agentflow.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/** 多实例调度租约锁：同一 lock_key 同一时间只允许一个持有者。 */
@Data
@TableName("scheduler_lock")
public class SchedulerLock {

    @TableId(value = "lock_key", type = IdType.INPUT)
    private String lockKey;
    private String owner;
    private LocalDateTime expiresAt;
    private LocalDateTime createdAt;
}
