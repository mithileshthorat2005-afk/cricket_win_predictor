package com.example.cricket.repository;

import com.example.cricket.model.Match;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface MatchRepository extends JpaRepository<Match, Long> {
    List<Match> findByStatusOrderByUpdatedAtDesc(String status);
}
