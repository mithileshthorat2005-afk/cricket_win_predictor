package com.example.cricket.exception;

/** 400: the request is well-formed but invalid for the current match state. */
public class InvalidMatchStateException extends RuntimeException {
    public InvalidMatchStateException(String message) {
        super(message);
    }
}
