import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Scale, BookOpen, MessageCircle, Search, Send } from 'lucide-react';
import { marked } from 'marked';

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
    const [currentSection, setCurrentSection] = useState('main');
    const [messages, setMessages] = useState([]);
    const [inputMessage, setInputMessage] = useState('');
    const [isProcessing, setIsProcessing] = useState(false);
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!inputMessage.trim()) return;

        const newMessage = { text: inputMessage, isBot: false };
        setMessages(prev => [...prev, newMessage]);
        setInputMessage('');
        setIsProcessing(true);

        // Start SSE connection
        const evtSource = new EventSource(`${API_BASE_URL}chat/stream`, {
            method: 'POST',
            body: JSON.stringify({ query: inputMessage, section: currentSection }),
            headers: { 'Content-Type': 'application/json' }
        });

        evtSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.message) {
                setMessages(prev => [...prev, { text: data.message, isBot: true }]);
            }
            if (event.data === '[DONE]') {
                evtSource.close();  // Close the connection when done
                setIsProcessing(false);
            }
        };

        evtSource.onerror = (err) => {
            console.error("EventSource failed:", err);
            evtSource.close();  // Close on error
            setIsProcessing(false);
        };
    };

    return (
        <div className="flex h-screen bg-gray-100">
            {/* Chat Area */}
            <div className="flex-1 flex flex-col">
                <div className="h-14 border-b border-gray-200 flex items-center justify-between px-4 bg-white">
                    <h1 className="text-lg font-semibold text-gray-800">Chat</h1>
                    {isProcessing && <span>Processing...</span>}
                </div>
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {messages.map((msg, index) => (
                        <div key={index} className={msg.isBot ? 'text-blue-500' : 'text-black'}>
                            {msg.text}
                        </div>
                    ))}
                    <div ref={messagesEndRef} />
                </div>
                <div className="border-t border-gray-200 p-4 bg-white">
                    <form onSubmit={handleSubmit} className="flex gap-2">
                        <input
                            type="text"
                            value={inputMessage}
                            onChange={(e) => setInputMessage(e.target.value)}
                            placeholder="Type your message..."
                            className="flex-1 rounded-lg border border-gray-300 px-4 py-2"
                        />
                        <button type="submit" className="bg-blue-600 text-white rounded-lg px-4 py-2">Send</button>
                    </form>
                </div>
            </div>
        </div>
    );
}

export default App;

export default App;
