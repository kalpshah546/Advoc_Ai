import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from '../api/axios';
import toast from 'react-hot-toast';
import { useAuth } from '../context/AuthContext';
import { Card, CardContent, CardHeader, CardTitle } from "@/Components/ui/Card";
import { Button } from "@/Components/ui/button";
import { Input } from "@/Components/ui/Input";
import { Send, ArrowLeft } from 'lucide-react';

const Chat = () => {
  const { conversationId } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [messages, setMessages] = useState([]);
  const [newMessage, setNewMessage] = useState('');
  const [conversation, setConversation] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (conversationId) {
      loadMessages();
      loadConversation();
      const interval = setInterval(loadMessages, 3000);
      return () => clearInterval(interval);
    }
  }, [conversationId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadMessages = async () => {
    try {
      const response = await axios.get(`api/chat/conversations/${conversationId}/messages/`);
      setMessages(response.data || []);
    } catch (err) {
      if (err.response?.status !== 404) {
        toast.error(err.response?.data?.error || 'Failed to load messages.');
      }
    }
  };

  const loadConversation = async () => {
    try {
      const response = await axios.get('api/chat/conversations/');
      const conversations = response.data.results || response.data || [];
      const conv = conversations.find(c => c.id === conversationId);
      if (conv) setConversation(conv);
    } catch (err) {
      console.error('Failed to load conversation:', err);
    } finally {
      setLoading(false);
    }
  };

  const sendMessage = async () => {
    if (!newMessage.trim()) return;
    setSending(true);
    try {
      await axios.post(`api/chat/conversations/${conversationId}/messages/`, {
        message: newMessage.trim(),
        message_type: 'text',
      });
      setNewMessage('');
      await loadMessages();
    } catch (err) {
      toast.error(err.response?.data?.error || 'Failed to send message.');
    } finally {
      setSending(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto py-10 animate-fade-in">
        <div className="text-center text-gray-400">Loading conversation...</div>
      </div>
    );
  }

  const otherUser = conversation?.client?.id === user?.id
    ? conversation?.lawyer
    : conversation?.client;

  return (
    <div className="container mx-auto py-6 h-[calc(100vh-var(--navbar-height))] flex flex-col animate-fade-in">
      <Card className="flex-1 flex flex-col bg-gray-800/40 backdrop-blur-sm border border-gray-700/50">
        <CardHeader className="border-b border-gray-700/50">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="sm" onClick={() => navigate(-1)} className="text-gray-400 hover:text-white">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back
            </Button>
            <div>
              <CardTitle className="text-white">{otherUser?.name || otherUser?.username || 'Chat'}</CardTitle>
              <p className="text-sm text-gray-400">{conversation?.lawyer?.id === user?.id ? 'Client' : 'Lawyer'}</p>
            </div>
          </div>
        </CardHeader>

        <CardContent className="flex-1 flex flex-col p-0 overflow-hidden">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 && (
              <div className="text-center text-gray-400 py-8">
                <p>No messages yet. Start the conversation!</p>
              </div>
            )}
            {messages.map((msg) => {
              const senderId = msg.sender?.id || msg.sender;
              const isOwn = String(senderId) === String(user?.id);
              return (
                <div key={msg.id} className={`flex ${isOwn ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[70%] rounded-lg p-3 ${
                      isOwn
                        ? 'bg-blue-600 text-white'
                        : msg.message_type === 'system'
                        ? 'bg-gray-700/50 text-gray-300 text-center mx-auto'
                        : 'bg-gray-700 text-white'
                    }`}
                  >
                    <p className="text-sm whitespace-pre-wrap">{msg.message}</p>
                    <p className="text-xs opacity-70 mt-1">{new Date(msg.created_at).toLocaleTimeString()}</p>
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>

          <div className="border-t border-gray-700/50 p-4">
            <div className="flex gap-2">
              <Input
                value={newMessage}
                onChange={(e) => setNewMessage(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Type a message..."
                disabled={sending}
                className="flex-1 bg-gray-700/50 border-gray-600 text-white placeholder-gray-400"
              />
              <Button onClick={sendMessage} disabled={sending || !newMessage.trim()} className="bg-blue-600 hover:bg-blue-700">
                <Send className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default Chat;
