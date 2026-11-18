package com.agentflow.dto;

import lombok.Data;

@Data
public class TextFileRequest {

    /** 存储目录内的相对路径，例如 reports/today.md */
    private String name;
    private String content = "";
    private String encoding = "utf-8";
    private Boolean overwrite = true;
    private Boolean append = false;
}
