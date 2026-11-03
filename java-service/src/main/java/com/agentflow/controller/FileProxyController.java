package com.agentflow.controller;

import com.agentflow.service.AiClient;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/files")
@RequiredArgsConstructor
public class FileProxyController {

    private final AiClient aiClient;

    @GetMapping("/{name}")
    public ResponseEntity<byte[]> file(@PathVariable String name) {
        if (name.contains("..") || name.contains("/")) {
            return ResponseEntity.badRequest().build();
        }
        byte[] content = aiClient.download("/files/" + name);
        return ResponseEntity.ok().contentType(mediaType(name)).body(content);
    }

    private MediaType mediaType(String name) {
        String lower = name.toLowerCase();
        if (lower.endsWith(".mp3")) {
            return MediaType.parseMediaType("audio/mpeg");
        }
        if (lower.endsWith(".wav")) {
            return MediaType.parseMediaType("audio/wav");
        }
        if (lower.endsWith(".png")) {
            return MediaType.IMAGE_PNG;
        }
        if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) {
            return MediaType.IMAGE_JPEG;
        }
        if (lower.endsWith(".webp")) {
            return MediaType.parseMediaType("image/webp");
        }
        if (lower.endsWith(".gif")) {
            return MediaType.IMAGE_GIF;
        }
        if (lower.endsWith(".svg")) {
            return MediaType.parseMediaType("image/svg+xml");
        }
        if (lower.endsWith(".mp4")) {
            return MediaType.parseMediaType("video/mp4");
        }
        if (lower.endsWith(".webm")) {
            return MediaType.parseMediaType("video/webm");
        }
        return MediaType.APPLICATION_OCTET_STREAM;
    }
}
