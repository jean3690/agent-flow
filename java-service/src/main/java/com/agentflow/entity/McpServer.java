package com.agentflow.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.FieldStrategy;
import lombok.Data;
import java.time.LocalDateTime;

@Data
@TableName("mcp_server")
public class McpServer {
    @TableId private Long id;
    private Long userId;
    private String name;
    private String url;
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String headersCipher;
    private String allowedTools;
    private String tools;
    private Integer timeoutMs;
    private Integer enabled;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
