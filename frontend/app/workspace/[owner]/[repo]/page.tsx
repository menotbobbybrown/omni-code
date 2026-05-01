'use client';

import React, { useState } from 'react';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import Editor from '@monaco-editor/react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import SessionTimeline from '@/components/SessionTimeline';
import AgentLogsPanel from '@/components/AgentLogsPanel';
import ModelPicker from '@/components/ModelPicker';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export default function WorkspacePage({ params }: { params: { owner: string, repo: string } }) {
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("// Select a file to edit");
  
  return (
    <div className="h-screen flex flex-col overflow-hidden bg-background">
      <header className="h-12 border-b flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-4">
          <h1 className="font-bold text-sm">{params.owner} / {params.repo}</h1>
          <ModelPicker />
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline">Deploy</Button>
          <Button size="sm">Commit</Button>
        </div>
      </header>

      <div className="flex-1 overflow-hidden">
        <PanelGroup direction="horizontal">
          <Panel defaultSize={20} minSize={15}>
            <div className="h-full border-r">
              <ScrollArea className="h-full">
                <div className="p-4">
                  <h3 className="text-xs font-semibold mb-2 uppercase text-muted-foreground">Files</h3>
                  <div className="space-y-1 text-sm">
                    {/* Mock file tree */}
                    <div className="cursor-pointer hover:bg-accent p-1 rounded" onClick={() => setActiveFile('main.py')}>main.py</div>
                    <div className="cursor-pointer hover:bg-accent p-1 rounded" onClick={() => setActiveFile('utils.py')}>utils.py</div>
                    <div className="cursor-pointer hover:bg-accent p-1 rounded" onClick={() => setActiveFile('requirements.txt')}>requirements.txt</div>
                  </div>
                </div>
              </ScrollArea>
            </div>
          </Panel>
          
          <PanelResizeHandle className="w-1 bg-border hover:bg-primary/50 transition-colors" />
          
          <Panel defaultSize={50}>
            <div className="h-full">
              <Editor
                height="100%"
                defaultLanguage="python"
                theme="vs-dark"
                value={fileContent}
                onChange={(v) => setFileContent(v || "")}
                options={{
                  minimap: { enabled: false },
                  fontSize: 14,
                }}
              />
            </div>
          </Panel>

          <PanelResizeHandle className="w-1 bg-border hover:bg-primary/50 transition-colors" />

          <Panel defaultSize={30} minSize={20}>
            <div className="h-full flex flex-col border-l">
              <Tabs defaultValue="chat" className="flex-1 flex flex-col">
                <TabsList className="mx-4 mt-4">
                  <TabsTrigger value="chat" className="flex-1">Chat</TabsTrigger>
                  <TabsTrigger value="history" className="flex-1">History</TabsTrigger>
                  <TabsTrigger value="logs" className="flex-1">Logs</TabsTrigger>
                </TabsList>
                
                <TabsContent value="chat" className="flex-1 flex flex-col p-4">
                  <ScrollArea className="flex-1 mb-4 border rounded p-2">
                    <div className="space-y-4 text-sm">
                      <div className="bg-muted p-2 rounded">Hello! I'm your AI agent. How can I help you with this repository today?</div>
                    </div>
                  </ScrollArea>
                  <div className="flex gap-2">
                    <Input placeholder="Type a message..." />
                    <Button>Send</Button>
                  </div>
                </TabsContent>
                
                <TabsContent value="history" className="flex-1 overflow-hidden">
                  <SessionTimeline threadId={1} />
                </TabsContent>

                <TabsContent value="logs" className="flex-1 overflow-hidden">
                  <AgentLogsPanel threadId={1} />
                </TabsContent>
              </Tabs>
            </div>
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
}
