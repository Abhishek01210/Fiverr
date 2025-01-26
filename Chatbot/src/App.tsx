import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Scale, BookOpen, MessageCircle, Search, Send } from 'lucide-react';
import { marked } from 'marked';

const API_BASE_URL = 'http://localhost:5000/';

interface Message {
  text: string;
  isBot: boolean;
  section: 'main' | 'for_against' | 'bare_acts';
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
  const [messages, setMessages] = useState<Message[]>([]);
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
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const loadChatHistory = async (section: Section) => {
    try {
      const response = await fetch(`${API_BASE_URL}history/${section}`);
      const data = await response.json();
      setHistory(prev => ({ ...prev, [section]: data }));
    } catch (error) {
      console.error('Error loading history:', error);
    }
  };

  const renderMessage = (message: Message) => (
    <div className={`flex ${message.isBot ? 'justify-start' : 'justify-end'} mb-5`}>
      <div className={`max-w-[70%] rounded-lg p-2 ${
        message.isBot ? 'bg-white shadow-sm' : 'bg-blue-600 text-white'
      }`}>
        {message.isBot ? (
          <div 
            className="message-content"
            dangerouslySetInnerHTML={{ __html: marked.parse(message.text) }} 
          />
        ) : (
          <div className="text-white">{message.text}</div>
        )}
      </div>
    </div>
  );

  const renderHistorySection = (period: keyof ChatHistory, label: string) => (
    <div className="history-section mb-4">
      <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
        {label}
      </h3>
      <div className="space-y-1">
        {history[currentSection][period].map((group, index) => (
          <div
            key={`${period}-${index}`}
            className="history-item text-sm text-gray-700 hover:bg-gray-100 rounded-lg px-3 py-2 cursor-pointer transition-colors"
          >
            {group.title}
          </div>
        ))}
      </div>
    </div>
  );
  
  useEffect(() => {
    const fetchSuggestions = async () => {
      if (searchTerm.length > 0) {
        try {
          const response = await fetch(
            `${API_BASE_URL}autocomplete?term=${encodeURIComponent(searchTerm)}&section=${currentSection}`
          );
          const data = await response.json();
          setSuggestions(data);
        } catch (error) {
          console.error('Error fetching suggestions:', error);
        }
      } else {
        setSuggestions([]);
      }
    };
  
    const handler = setTimeout(fetchSuggestions, 300);
    return () => clearTimeout(handler);
  }, [searchTerm, currentSection]);

  useEffect(() => {
    sections.forEach(loadChatHistory);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const switchSection = (section: Section) => {
    setCurrentSection(section);
    setCurrentChatId(activeSessions[section]);
    if (!activeSessions[section]) {
      loadChatHistory(section);
    }
  };

  useEffect(() => {
    const initialMessages = sections.map(section => ({
      text: "How can I help you today?",
      isBot: true,
      section: section
    }));
  
    if (messages.length === 0) {
      setMessages(initialMessages);
    }
  
    sections.forEach(loadChatHistory);
  }, []);

  const handleNewChat = async (section: Section) => {
    try {
      await fetch(`${API_BASE_URL}history/${section}/clear`, { method: 'POST' });
      
      setMessages(prev => [
        ...prev.filter(msg => msg.section !== section),
        { text: "How can I help you today?", isBot: true, section }
      ]);
      
      setCurrentChatId(null);
      setActiveSessions(prev => ({ ...prev, [section]: null }));
      loadChatHistory(section);
    } catch (error) {
      console.error('Error clearing chat history:', error);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputMessage.trim()) return;

    const newMessage: Message = { text: inputMessage, isBot: false, section: currentSection };
    setMessages(prev => [...prev, newMessage]);
    setInputMessage('');
    setIsProcessing(true);

    try {
      const response = await fetch(`${API_BASE_URL}chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: inputMessage,
          section: currentSection,
          chat_id: currentChatId
        }),
      });

      if (!response.ok) throw new Error('Network error');

      const reader = response.body?.getReader();
      if (!reader) return;

      let accumulatedContent = '';
      let newChatId = currentChatId;
      let isNewChat = !currentChatId;
  
      setMessages(prev => [
        ...prev,
        { text: '', isBot: true, section: currentSection }
      ]);
  
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
  
        const chunk = new TextDecoder().decode(value);
        const lines = chunk.split('\n');
  
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.replace('data: ', '');
            
            if (jsonStr === '[DONE]') {
              setMessages(prev => prev.map((msg, index) => 
                index === prev.length - 1 
                  ? { ...msg, text: accumulatedContent }
                  : msg
              ));
              continue;
            }
  
            try {
              const data = JSON.parse(jsonStr);
              if (data.content) {
                accumulatedContent += data.content;
                setMessages(prev => prev.map((msg, index) => 
                  index === prev.length - 1 
                    ? { ...msg, text: accumulatedContent }
                    : msg
                ));
                scrollToBottom();
              }

              if (data.chat_id && !newChatId) {
                newChatId = data.chat_id;
                setCurrentChatId(newChatId);
                setActiveSessions(prev => ({
                  ...prev,
                  [currentSection]: newChatId
                }));
              }
            } catch (parseError) {
              console.error('Parse error:', parseError);
            }
          }
        }
      }

      if (isNewChat) {
        await loadChatHistory(currentSection);
      }
    } catch (error) {
      console.error('API error:', error);
      setMessages(prev => [
        ...prev,
        { text: "Sorry, an error occurred", isBot: true, section: currentSection }
      ]);
    } finally {
      setIsProcessing(false);
    }
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
                        ? 'tab-active bg-blue-50 border-l-4 border-blue-500'
                        : 'hover:bg-gray-100'
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
            
            {suggestions.length > 0 && (
              <div className="absolute top-full left-0 right-0 bg-white shadow-lg rounded-lg mt-1 z-10 max-h-48 overflow-y-auto">
                {suggestions.map((suggestion, index) => (
                  <div
                    key={index}
                    className="px-4 py-2 hover:bg-gray-100 cursor-pointer text-sm"
                    onClick={() => {
                      setSearchTerm(suggestion);
                      setSuggestions([]);
                    }}
                  >
                    {suggestion}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Chat History */}
        <div className="px-4 mt-4 flex-1 overflow-y-auto space-y-4">
          {renderHistorySection('today', 'Today')}
          {renderHistorySection('yesterday', 'Yesterday')}
          {renderHistorySection('seven_days', '7 Days')}
          {renderHistorySection('thirty_days', '30 Days')}
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

        {/* Messages Container */}
        <div
          ref={messagesContainerRef}
          className="flex-1 overflow-y-auto p-4 messages-container"
        >
          {messages
            .filter(msg => msg.section === currentSection)
            .map((message, index) => (
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
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2 focus:outline-none focus:border-blue-500"
            />
            <button
              type="submit"
              className="bg-blue-600 text-white rounded-lg px-4 py-2 hover:bg-blue-700 transition-colors flex items-center gap-2"
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