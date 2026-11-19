package com.agentflow.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class RealtimeTranslationRequest {
    @NotBlank
    @Pattern(regexp = "qwen|mock")
    private String provider = "qwen";
    @NotBlank
    @Pattern(regexp = "[a-z]{2,3}(-[a-z]{2,4})?")
    private String targetLang = "en";
    @Size(max = 255)
    private String apiHost = "";
    @NotBlank
    @Size(max = 80)
    private String voice = "Tina";
    private boolean outputAudio = true;
}
