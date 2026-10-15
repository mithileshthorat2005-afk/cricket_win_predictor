package com.example.cricket.exception;

/** 404: the referenced match does not exist. */
public class MatchNotFoundException extends RuntimeException {
    public MatchNotFoundException(Long matchId) {
        super("Match not found: " + matchId);
    }
}
