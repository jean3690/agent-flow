package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.dto.KnowledgeBaseRequest;
import com.agentflow.dto.KnowledgeBaseVO;
import com.agentflow.dto.KnowledgeChunkVO;
import com.agentflow.dto.KnowledgeDocumentVO;
import com.agentflow.dto.KnowledgePreviewRequest;
import com.agentflow.dto.KnowledgeSearchHitVO;
import com.agentflow.dto.KnowledgeSearchRequest;
import com.agentflow.dto.KnowledgeTextRequest;
import com.agentflow.security.UserContext;
import com.agentflow.service.KnowledgeBaseService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

@RestController
@RequestMapping("/api/knowledge-bases")
@RequiredArgsConstructor
public class KnowledgeBaseController {

    private final KnowledgeBaseService knowledgeBaseService;

    @GetMapping
    public ApiResponse<List<KnowledgeBaseVO>> list() {
        return ApiResponse.ok(knowledgeBaseService.list(UserContext.get()));
    }

    @PostMapping
    public ApiResponse<KnowledgeBaseVO> create(@Valid @RequestBody KnowledgeBaseRequest request) {
        return ApiResponse.ok(knowledgeBaseService.create(request, UserContext.get()));
    }

    @GetMapping("/{id}")
    public ApiResponse<KnowledgeBaseVO> detail(@PathVariable Long id) {
        return ApiResponse.ok(knowledgeBaseService.detail(id, UserContext.get()));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable Long id) {
        knowledgeBaseService.delete(id, UserContext.get());
        return ApiResponse.ok();
    }

    @GetMapping("/{id}/documents")
    public ApiResponse<List<KnowledgeDocumentVO>> documents(@PathVariable Long id) {
        return ApiResponse.ok(knowledgeBaseService.documents(id, UserContext.get()));
    }

    @PostMapping("/{id}/documents/text")
    public ApiResponse<KnowledgeDocumentVO> importText(@PathVariable Long id,
                                                       @RequestBody KnowledgeTextRequest request) {
        return ApiResponse.ok(knowledgeBaseService.importText(id, request.getTitle(), request.getContent(), "TEXT", UserContext.get()));
    }

    @PostMapping("/{id}/documents/upload")
    public ApiResponse<KnowledgeDocumentVO> upload(@PathVariable Long id,
                                                   @RequestParam("file") MultipartFile file) {
        return ApiResponse.ok(knowledgeBaseService.uploadTextFile(id, file, UserContext.get()));
    }

    @DeleteMapping("/{id}/documents/{documentId}")
    public ApiResponse<Void> deleteDocument(@PathVariable Long id, @PathVariable Long documentId) {
        knowledgeBaseService.deleteDocument(id, documentId, UserContext.get());
        return ApiResponse.ok();
    }

    @PostMapping("/{id}/documents/{documentId}/preview")
    public ApiResponse<List<KnowledgeChunkVO>> preview(@PathVariable Long id,
                                                       @PathVariable Long documentId,
                                                       @RequestBody(required = false) KnowledgePreviewRequest request) {
        return ApiResponse.ok(knowledgeBaseService.previewChunks(id, documentId,
                request == null ? null : request.getChunkSize(),
                request == null ? null : request.getChunkOverlap(), UserContext.get()));
    }

    @PostMapping("/{id}/documents/{documentId}/index")
    public ApiResponse<KnowledgeDocumentVO> index(@PathVariable Long id, @PathVariable Long documentId) {
        return ApiResponse.ok(knowledgeBaseService.indexDocument(id, documentId, UserContext.get()));
    }

    @PostMapping("/{id}/search")
    public ApiResponse<List<KnowledgeSearchHitVO>> search(@PathVariable Long id,
                                                         @Valid @RequestBody KnowledgeSearchRequest request) {
        return ApiResponse.ok(knowledgeBaseService.search(id, request.getQuery(), request.getTopK(), UserContext.get()));
    }
}
