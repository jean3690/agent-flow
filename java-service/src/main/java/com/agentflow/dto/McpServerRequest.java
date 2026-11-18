package com.agentflow.dto;

import jakarta.validation.constraints.*;
import lombok.Data;
import java.util.List;
import java.util.Map;

@Data
public class McpServerRequest {
    @NotBlank @Size(max = 128) private String name;
    @NotBlank @Size(max = 2048) private String url;
    @Size(max = 20) private Map<String, String> headers;
    private boolean clearHeaders;
    @NotNull @Size(max = 100) private List<String> allowedTools = List.of();
    @Min(1000) @Max(60000) private int timeoutMs = 15000;
    private boolean enabled = true;
}
