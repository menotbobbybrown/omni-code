'use client';

import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Code, Terminal, Sparkles, CheckCircle2, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

interface LiveCodingProps {
  taskId: string;
  className?: string;
}

interface LogEntry {
  message: string;
  type: 'thought' | 'action' | 'info' | 'warning' | 'error' | 'token';
  timestamp: number;
}

export function LiveCodingView({ taskId, className }: LiveCodingProps) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [currentThought, setCurrentThought] = useState<string>("");
  const [lastAction, setLastAction] = useState<string>("");
  const [isStreaming, setIsStreaming] = useState(false);

  useEffect(() => {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const eventSource = new EventSource(`${baseUrl}/api/stream/agent/${taskId}`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'token') {
          setIsStreaming(true);
          setLastAction(prev => prev + data.token);
        } else {
          setIsStreaming(false);
          const newLog: LogEntry = {
            message: data.message,
            type: data.type,
            timestamp: data.timestamp || Date.now()
          };
          
          if (data.type === 'thought') {
            setCurrentThought(data.message);
          } else if (data.type === 'action') {
            setLastAction(data.message);
          }
          
          setLogs(prev => [...prev, newLog].slice(-10));
        }
      } catch (e) {
        console.error('Failed to parse SSE data', e);
      }
    };

    return () => {
      eventSource.close();
    };
  }, [taskId]);

  return (
    <div className={cn("flex flex-col h-full bg-[#09090b] border-t border-border", className)}>
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-[#18181b]">
        <div className="relative">
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <div className="absolute inset-0 w-2 h-2 rounded-full bg-green-500 animate-ping opacity-75" />
        </div>
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Live Coding Agent</span>
      </div>

      <div className="flex-1 overflow-hidden p-4 space-y-4">
        <AnimatePresence mode="wait">
          {currentThought && (
            <motion.div 
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg"
            >
              <div className="flex items-center gap-2 mb-1 text-blue-400">
                <Sparkles className="w-3.5 h-3.5" />
                <span className="text-[10px] font-bold uppercase">Current Thought</span>
              </div>
              <p className="text-sm text-blue-100">{currentThought}</p>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
          <div className="flex items-center gap-2 mb-2 text-zinc-400">
            <Terminal className="w-3.5 h-3.5" />
            <span className="text-[10px] font-bold uppercase">Active Operation</span>
          </div>
          <div className="font-mono text-sm text-zinc-300 break-all bg-black/50 p-2 rounded">
            {lastAction}
            {isStreaming && <span className="inline-block w-2 h-4 ml-1 bg-primary animate-pulse" />}
          </div>
        </div>

        <div className="space-y-2 overflow-y-auto max-h-[200px] pr-2 scrollbar-thin scrollbar-thumb-zinc-800">
          {logs.filter(l => l.type !== 'token' && l.type !== 'thought').map((log, i) => (
            <div key={i} className="flex gap-2 text-xs">
              <span className="text-muted-foreground opacity-50">
                {new Date(log.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
              <span className={cn(
                log.type === 'error' ? 'text-red-400' :
                log.type === 'warning' ? 'text-yellow-400' :
                log.type === 'action' ? 'text-green-400' :
                'text-zinc-400'
              )}>
                {log.message}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
