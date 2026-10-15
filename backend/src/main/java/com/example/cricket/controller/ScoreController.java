package com.example.cricket.controller;

import com.example.cricket.service.CommentaryService;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * Legacy score endpoint, ported from the original livecricket project.
 * Kept for backward compatibility with the /topic/live demo client.
 *
 * Hardened vs the original: AI commentary failure no longer fails the
 * request - 'commentary' is simply null when Ollama is disabled/unavailable.
 */
@RestController
@RequestMapping("/score")
public class ScoreController {

    private final SimpMessagingTemplate template;
    private final CommentaryService commentaryService;

    public ScoreController(SimpMessagingTemplate template, CommentaryService commentaryService) {
        this.template = template;
        this.commentaryService = commentaryService;
    }

    @PostMapping
    public Map<String, Object> update(@RequestBody Map<String, Object> score) {
        String commentary = commentaryService.generate(String.valueOf(score));

        Map<String, Object> response = new HashMap<>();
        response.put("score", score);
        response.put("commentary", commentary); // null when AI commentary is off

        template.convertAndSend("/topic/live", response);
        return response;
    }
}
