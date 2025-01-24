import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Scale, BookOpen, MessageCircle, Search, Send } from 'lucide-react';
import { marked } from 'marked';
import useSSE from './hooks/useSSE';

const API_BASE_URL = 'https://chatbot-u30628.vm.elestio.app/';

interface Message {
  text: string;
  isBot: boolean;
}

interface ChatHistory {
  today: ChatGroup[];
  yesterday: ChatGroup[];
  seven_days: ChatGroup[];
  thirty_days: ChatGroup[];
}

interface ChatGroup {
  title: string;
  timestamp: string;
  messages: HistoryMessage[];
}

interface HistoryMessage {
  chat_id: string;
  query: string;
  response: string;
  timestamp: string;
}

const sections = ['main', 'for_against', 'bare_acts'] as const;
type Section = typeof sections[number];

const sectionTitles: Record<Section, string> = {
  main: 'Chat',
  for_against: 'For/Against',
  bare_acts: 'Explanations to Sections'
};

const sectionIcons = {
  main: MessageSquare,
  for_against: Scale,
  bare_acts: BookOpen
};

function App() {
  const [currentSection, setCurrentSection] = useState<Section>('main');
  const [messages, setMessages] = useState<Record<Section, Message[]>>({
    main: [{ text: "How can I help you today?", isBot: true }],
    for_against: [{ text: "How can I help you today?", isBot: true }],
    bare_acts: [{ text: "How can I help you today?", isBot: true }]
  });
  const [inputMessage, setInputMessage] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [history, setHistory] = useState<Record<Section, ChatHistory>>({
    main: { today: [], yesterday: [], seven_days: [], thirty_days: [] },
    for_against: { today: [], yesterday: [], seven_days: [], thirty_days: [] },
    bare_acts: { today: [], yesterday: [], seven_days: [], thirty_days: [] }
  });
  const [currentChatId, setCurrentChatId] = useState<string | null>(null);
  const [activeSessions, setActiveSessions] = useState<Record<Section, string | null>>({
    main: null,
    for_against: null,
    bare_acts: null
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const botResponseRef = useRef<string>('');

  const SSE_URL = `${API_BASE_URL}events`;
  const { data: sseData, error: sseError } = useSSE(SSE_URL);

  // Add new state for SSE notifications
  const [notifications, setNotifications] = useState<string[]>([]);
  
  // Handle SSE data
  useEffect(() => {
    if (sseData) {
      setNotifications(prev => [...prev, sseData]);
    }
  }, [sseData]);
  
  // Handle SSE errors
  useEffect(() => {
    if (sseError) {
      console.error('SSE Error:', sseError);
    }
  }, [sseError]);
  
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    sections.forEach(loadChatHistory);
  }, []);

  const loadChatHistory = async (section: Section) => {
    try {
      const response = await fetch(`${API_BASE_URL}history/${section}`);
      const data = await response.json();
      setHistory(prev => ({
        ...prev,
        [section]: data
      }));
    } catch (error) {
      console.error('Error loading chat history:', error);
    }
  };

  const handleNewChat = (section: Section) => {
    setCurrentChatId(null);
    setActiveSessions(prev => ({
      ...prev,
      [section]: null
    }));
    setMessages(prev => ({
      ...prev,
      [section]: [{ text: "How can I help you today?", isBot: true }]
    }));
  };

  const switchSection = (section: Section) => {
    setCurrentSection(section);
    setCurrentChatId(activeSessions[section]);
    
    if (!activeSessions[section]) {
      loadChatHistory(section);
    }
  };

const handleSubmit = async (e: React.FormEvent) => {
  e.preventDefault();
  if (!inputMessage.trim() || isProcessing) return;

  const newMessage = { text: inputMessage, isBot: false };
  setMessages(prev => ({
    ...prev,
    [currentSection]: [...prev[currentSection], newMessage]
  }));
  setInputMessage('');
  setIsProcessing(true);
  botResponseRef.current = '';

try {
  const response = await fetch(`${API_BASE_URL}chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: inputMessage,
      section: currentSection,
      chat_id: currentChatId
    })
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP error: ${response.status} - ${errorText}`);
  }

  // Create a temporary bot message
  setMessages(prev => ({
    ...prev,
    [currentSection]: [...prev[currentSection], { text: '', isBot: true }]
  }));

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();

  if (!reader) {
    throw new Error('Unable to read response stream');
  }

  let accumulatedResponse = '';

  while (true) {
    const { done, value } = await reader.read();
    
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    const lines = chunk.split('\n');

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const content = line.slice(6).trim();
          
          if (content === '[DONE]') {
            break; // End of stream
          } else if (content.startsWith('{')) {
            const parsedData = JSON.parse(content);
            
            if (parsedData.error) {
              throw new Error(parsedData.error);
            }
            
            if (parsedData.content) {
              // Append new content incrementally
              accumulatedResponse += parsedData.content;
              setMessages(prev => {
                const messages = [...prev[currentSection]];
                const lastMessage = messages[messages.length - 1];
                if (lastMessage?.isBot) {
                  messages[messages.length - 1] = {
                    text: accumulatedResponse,
                    isBot: true
                  };
                }
                return { ...prev, [currentSection]: messages };
              });
            }
          }
        } catch (parseError) {
          console.error('Parsing error:', parseError);
        }
      }
    }
  }
} catch (error) {
  const errorMessage = error instanceof Error ? error.message : 'Unknown error';
  setMessages(prev => ({
    ...prev,
    [currentSection]: [...prev[currentSection], { 
      text: `Error: ${errorMessage}`, 
      isBot: true 
    }]
  }));
} finally {
  setIsProcessing(false);
}
  
const renderMessage = (message: Message) => {
  const isBot = message.isBot;
  const formattedText = marked.parse(message.text);

  return (
    <div className={`flex ${isBot ? 'justify-start' : 'justify-end'}`}>
      <div
        className={`max-w-[80%] rounded-lg p-4 ${
          isBot
            ? 'bg-white text-gray-800 shadow-sm'
            : 'bg-blue-600 text-white'
        }`}
      >
        <div
          className="prose max-w-none"
          dangerouslySetInnerHTML={{ __html: formattedText }}
        />
      </div>
    </div>
  );
};

const renderHistorySection = (period: keyof ChatHistory, title: string) => {
  const filteredChats = history[currentSection][period].filter(chat =>
    !searchTerm ||
    chat.messages.some(msg =>
      msg.query.toLowerCase().includes(searchTerm.toLowerCase()) ||
      msg.response.toLowerCase().includes(searchTerm.toLowerCase())
    )
  );

  if (filteredChats.length === 0) return null;

    return (
      <div>
        <h3 className="text-xs font-semibold text-gray-500 mb-2">{title}</h3>
        <div className="space-y-1">
          {filteredChats.map((chat, index) => (
            <button
              key={index}
              onClick={() => {
                // Handle chat selection
              }}
              className="w-full text-left px-3 py-2 rounded text-sm hover:bg-gray-100 transition-colors"
            >
              {chat.title || "New Chat"}
            </button>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="flex h-screen bg-gray-100">
      {/* Sidebar */}
      <div className="w-64 bg-white border-r border-gray-200 flex flex-col">
        <div className="border-b border-gray-200">
          <div className="p-4 space-y-2">
            <button
              onClick={() => handleNewChat(currentSection)}
              className="w-full flex items-center justify-center gap-2 bg-blue-600 text-white rounded-lg py-2 px-4 hover:bg-blue-700 transition-colors"
            >
              <MessageCircle className="w-5 h-5" />
              <span>New chat</span>
            </button>
            <div className="space-y-1">
              {sections.map(section => {
                const Icon = sectionIcons[section];
                return (
                  <button
                    key={section}
                    onClick={() => switchSection(section)}
                    className={`w-full text-left px-4 py-2 rounded-lg flex items-center gap-2 transition-colors ${
                      currentSection === section
                        ? 'bg-gray-100'
                        : 'hover:bg-gray-50'
                    }`}
                  >
                    <Icon className="w-5 h-5" />
                    <span>{sectionTitles[section]}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Search Section */}
        <div className="px-4 py-2">
          <div className="relative">
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search messages"
              className="w-full pl-9 pr-4 py-2 bg-gray-100 border border-transparent rounded-lg text-sm focus:outline-none focus:border-gray-300 transition-colors"
            />
            <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 transform -translate-y-1/2" />
          </div>
        </div>

        {/* In the sidebar div, after search section */}
        <div className="px-4 py-2 border-b border-gray-200">
          <h3 className="text-xs font-semibold text-gray-500 mb-2">Real-Time Updates</h3>
          <div className="space-y-1 h-32 overflow-y-auto">
            {notifications.map((msg, index) => (
              <div key={index} className="text-xs p-2 bg-gray-100 rounded">
                {msg}
              </div>
            ))}
            {notifications.length === 0 && (
              <p className="text-xs text-gray-400">No updates</p>
            )}
          </div>
        </div>
        
        {/* Chat History */}
        <div className="px-4 mt-4 flex-1 overflow-y-auto space-y-4">
          {renderHistorySection('today', 'Today')}
          {renderHistorySection('yesterday', 'Yesterday')}
          {renderHistorySection('seven_days', 'Last 7 Days')}
          {renderHistorySection('thirty_days', 'Last 30 Days')}
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Chat Header */}
        <div className="h-14 border-b border-gray-200 flex items-center justify-between px-4 bg-white">
          <h1 className="text-lg font-semibold text-gray-800">
            {sectionTitles[currentSection]}
          </h1>
          {isProcessing && (
            <div className="animate-pulse flex items-center">
              <div className="h-2 w-2 bg-green-500 rounded-full mr-2" />
              <span className="text-sm text-gray-500">Processing...</span>
            </div>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-gray-50">
          {messages[currentSection].map((message, index) => (
            <div key={index}>{renderMessage(message)}</div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="border-t border-gray-200 p-4 bg-white">
          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              placeholder="Type your message..."
              disabled={isProcessing}
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2 focus:outline-none focus:border-blue-500 disabled:bg-gray-50 disabled:cursor-not-allowed"
            />
            <button
              type="submit"
              disabled={isProcessing || !inputMessage.trim()}
              className="bg-blue-600 text-white rounded-lg px-4 py-2 hover:bg-blue-700 transition-colors flex items-center gap-2 disabled:bg-blue-400 disabled:cursor-not-allowed"
            >
              <Send className="w-5 h-5" />
              <span>Send</span>
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default App;
