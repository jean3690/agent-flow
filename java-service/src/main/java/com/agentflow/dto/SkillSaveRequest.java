package com.agentflow.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class SkillSaveRequest {
    @NotBlank @Size(max = 200000) private String content;
}
