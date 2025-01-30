import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Scale, BookOpen, MessageCircle, Search, Send } from 'lucide-react';
import { marked } from 'marked';

const API_BASE_URL = 'https://chatbot-python-u30628.vm.elestio.app/';

type MessageSection = Exclude<Section, 'for_against'>;

interface Message {
  text: string;
  isBot: boolean;
  section: MessageSection; // Now only allows 'main' | 'bare_acts'
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

interface Judgment {
  id: string;  // Changed to string to match DocumentID
  name: string;
  intro: string;
}

interface JudgmentsResponse {
  status: string;
  count: number;
  data: Judgment[];
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

  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const [isLoadingJudgments, setIsLoadingJudgments] = useState(true);
  // Update state
  const [judgments, setJudgments] = useState<Judgment[]>([]);
  // Update state type
  const [expandedJudgments, setExpandedJudgments] = useState<Set<string>>(new Set());

  const [messageSearchTerm, setMessageSearchTerm] = useState('');
  const [judgmentSearchTerm, setJudgmentSearchTerm] = useState('');

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const fetchJudgments = async () => {
    try {
      setIsLoadingJudgments(true);
      const response = await fetch(`${API_BASE_URL}judgments`);
      
      // Update fetchJudgments
      const data: JudgmentsResponse = await response.json();
      setJudgments(data.data);
    } catch (error) {
      console.error('Error loading judgments:', error);
    } finally {
      setIsLoadingJudgments(false);
    }
  };

  // Modify useEffect to load judgments immediately
  useEffect(() => {
    fetchJudgments();
    sections.forEach(loadChatHistory);
  }, []);

  // Modified loadChatHistory function
  const loadChatHistory = async (section: Section) => {
    try {
      setIsLoadingHistory(true);
      const response = await fetch(`${API_BASE_URL}history/${section}`);
      const data = await response.json();
      setHistory(prev => ({ ...prev, [section]: data }));
    } catch (error) {
      console.error('Error loading history:', error);
    } finally {
      setIsLoadingHistory(false);
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

  // Update renderJudgments filter
  const renderJudgments = () => {
    const filteredJudgments = judgments.filter(judgment =>
      judgment.name.toLowerCase().includes(judgmentSearchTerm.toLowerCase()) ||
      judgment.intro.toLowerCase().includes(judgmentSearchTerm.toLowerCase())
    );
  
    return (
      <div className="space-y-4">
        {isLoadingJudgments ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
          </div>
        ) : filteredJudgments.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            No judgments found matching your search
          </div>
        ) : (
          filteredJudgments.map((judgment) => (
            <div key={judgment.id} className="border rounded-lg p-4 bg-white shadow-sm">
              <div 
                className="flex justify-between items-center cursor-pointer"
                onClick={() => toggleJudgment(judgment.id)}
              >
                <h3 className="font-bold text-gray-800">
                  {judgment.name || "Untitled Judgment"}
                </h3>
                <button className="p-1 transform transition-transform">
                  <svg 
                    className={`w-5 h-5 text-gray-600 transform transition-transform ${
                      expandedJudgments.has(judgment.id) ? 'rotate-180' : ''
                    }`}
                    fill="none" 
                    stroke="currentColor" 
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
              </div>
              {expandedJudgments.has(judgment.id) && (
                <div className="mt-2 text-gray-600 transition-all duration-300">
                  {judgment.intro}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    );
  }; 

  // Update useEffect for suggestions
  useEffect(() => {
    if (currentSection === 'for_against') {
      setSuggestions([]);
      return;
    }

    const fetchSuggestions = async () => {
      if (messageSearchTerm.length > 0) {
        try {
          const response = await fetch(
            `${API_BASE_URL}autocomplete?term=${encodeURIComponent(messageSearchTerm)}&section=${currentSection}`
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
  }, [messageSearchTerm, currentSection]); // Changed dependency to messageSearchTerm
  
  useEffect(() => {
    sections.forEach(loadChatHistory);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (currentSection === 'for_against' && judgments.length === 0) {
      console.log('Fetching judgments...');
      fetchJudgments();
    }
  }, [currentSection, judgments.length]); // Fixed dependencies

  // Update the existing switchSection function in your component
  const switchSection = (section: Section) => {
    setCurrentSection(section);
    setMessageSearchTerm('');  // Clear message search
    setJudgmentSearchTerm(''); // Clear judgment search
    
    if (section === 'for_against') {
      setCurrentChatId(null);
      setActiveSessions(prev => ({ ...prev, [section]: null }));
    } else {
      setCurrentChatId(activeSessions[section]);
      if (!activeSessions[section]) {
        loadChatHistory(section);
      }
    }
    
    if (section === 'for_against') {
      fetchJudgments();
    }
  };

  const toggleJudgment = (id: string) => { // Changed from number to string
    setExpandedJudgments(prev => {
      const newSet = new Set(prev);
      newSet.has(id) ? newSet.delete(id) : newSet.add(id);
      return newSet;
    });
  };

  useEffect(() => {
  // Update your initial messages accordingly
  const initialMessages = sections
    .filter(section => section !== 'for_against')
    .map(section => ({
      text: "How can I help you today?",
      isBot: true,
      section: section as MessageSection
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
        { 
          text: "How can I help you today?", 
          isBot: true, 
          section: section as MessageSection // Added type assertion
        }
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
    if (!inputMessage.trim() || currentSection === 'for_against') return;

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
            value={messageSearchTerm}
            onChange={(e) => setMessageSearchTerm(e.target.value)}
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
                    setMessageSearchTerm(suggestion);
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
              className="flex-1 overflow-y-auto p-4 messages-container">
              {currentSection === 'for_against' ? (
                renderJudgments()
              ) : (
                messages
                  .filter(msg => msg.section === currentSection)
                  .map((message, index) => (
                    // ▼▼▼ Update this div's key prop ▼▼▼
                    <div key={`${message.section}-${index}-${message.text.slice(0,5)}`}>
                      {renderMessage(message)}
                    </div>
                    // ▲▲▲ Updated key here ▲▲▲
                  ))
              )}
              <div ref={messagesEndRef} />
            </div>

        {/* Input Area */}
        {currentSection === 'for_against' ? (
        <div className="border-t border-gray-200 p-4 bg-white">
          <div className="flex gap-2">
            <input
              type="text"
              value={judgmentSearchTerm}
              onChange={(e) => setJudgmentSearchTerm(e.target.value)}
              placeholder="Search judgments..."
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2 focus:outline-none focus:border-blue-500"
            />
            <Search className="w-5 h-5 text-gray-400 mt-2" />
          </div>
        </div>
      ) : (
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
        )}
      </div>
    </div>
  );
}

export default App;
