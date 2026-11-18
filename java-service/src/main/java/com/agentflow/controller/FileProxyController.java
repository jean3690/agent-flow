package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.common.BizException;
import com.agentflow.dto.TextFileRequest;
import com.agentflow.service.AiClient;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.MediaTypeFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.util.UriUtils;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 文件代理：GET 下载保持匿名（供 img/video/audio 标签直接引用），
 * 上传 / 列表 / 删除与文本写入需要登录或 API Key。
 */
@RestController
@RequestMapping("/api/files")
@RequiredArgsConstructor
public class FileProxyController {

    private final AiClient aiClient;

    @GetMapping
    public ApiResponse<List<JsonNode>> list(
            @RequestParam(value = "prefix", defaultValue = "") String prefix,
            @RequestParam(value = "limit", defaultValue = "500") int limit) {
        StringBuilder path = new StringBuilder("/v1/files?limit=").append(Math.max(1, Math.min(limit, 5000)));
        if (prefix != null && !prefix.isBlank()) {
            path.append("&prefix=").append(URLEncoder.encode(prefix, StandardCharsets.UTF_8));
        }
        return ApiResponse.ok(aiClient.dataList(path.toString()));
    }

    @PostMapping({"", "/upload"})
    public ApiResponse<JsonNode> upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "name", required = false) String name) throws IOException {
        if (file == null || file.isEmpty()) {
            throw new BizException("上传文件为空");
        }
        String targetName = (name == null || name.isBlank()) ? file.getOriginalFilename() : name;
        return ApiResponse.ok(aiClient.uploadFile(targetName, file.getBytes(), file.getContentType()));
    }

    @PostMapping("/text")
    public ApiResponse<JsonNode> writeText(@RequestBody TextFileRequest request) {
        if (request.getName() == null || request.getName().isBlank()) {
            throw new BizException("文件路径不能为空");
        }
        return ApiResponse.ok(aiClient.postJson("/v1/files/text", request).path("data"));
    }

    @DeleteMapping("/{*name}")
    public ApiResponse<JsonNode> delete(@PathVariable String name) {
        String path = safePath(name);
        return ApiResponse.ok(aiClient.delete("/v1/files/" + encodePath(path)));
    }

    @GetMapping("/{*name}")
    public ResponseEntity<byte[]> file(
            @PathVariable String name,
            @RequestParam(value = "download", defaultValue = "false") boolean download) {
        String path = safePath(name);
        byte[] content = aiClient.download("/files/" + encodePath(path));
        String filename = path.substring(path.lastIndexOf('/') + 1);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(mediaType(filename));
        if (download) {
            headers.setContentDisposition(ContentDisposition.attachment()
                    .filename(filename, StandardCharsets.UTF_8)
                    .build());
        }
        return new ResponseEntity<>(content, headers, HttpStatus.OK);
    }

    private String safePath(String name) {
        String cleaned = name == null ? "" : name.replace('\\', '/').replaceFirst("^/+", "");
        if (cleaned.isBlank() || cleaned.contains("\0")) {
            throw new BizException("非法文件路径");
        }
        for (String part : cleaned.split("/")) {
            if (part.equals(".") || part.equals("..")) {
                throw new BizException("非法文件路径: " + name);
            }
        }
        return cleaned;
    }

    private String encodePath(String path) {
        return Arrays.stream(path.split("/"))
                .map(part -> UriUtils.encodePathSegment(part, StandardCharsets.UTF_8))
                .collect(Collectors.joining("/"));
    }

    private MediaType mediaType(String name) {
        return MediaTypeFactory.getMediaType(name)
                .orElseGet(() -> {
                    if (name.toLowerCase().endsWith(".svg")) {
                        return MediaType.parseMediaType("image/svg+xml");
                    }
                    return MediaType.APPLICATION_OCTET_STREAM;
                });
    }
}
