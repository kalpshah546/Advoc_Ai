import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from '../api/axios';
import toast from 'react-hot-toast';
import { useAuth } from '../context/AuthContext';
import { Card, CardContent } from "@/Components/ui/Card";
import { Button } from "@/Components/ui/button";
import { Input } from "@/Components/ui/Input";
import { MessageSquare, ArrowRight, Clock, Star, Video } from 'lucide-react';

const StarRatingInput = ({ value, onChange }) => (
  <div className="flex gap-1">
    {[1, 2, 3, 4, 5].map((star) => (
      <button
        key={star}
        type="button"
        onClick={() => onChange(star)}
        className="focus:outline-none"
      >
        <Star
          className={`w-5 h-5 ${star <= value ? 'text-yellow-400 fill-yellow-400' : 'text-gray-500'}`}
        />
      </button>
    ))}
  </div>
);

const StarRatingDisplay = ({ score, size = 'sm' }) => {
  const sizeClass = size === 'lg' ? 'w-5 h-5' : 'w-4 h-4';
  return (
    <div className="flex items-center gap-1">
      {[1, 2, 3, 4, 5].map((star) => (
        <Star
          key={star}
          className={`${sizeClass} ${star <= Math.round(score) ? 'text-yellow-400 fill-yellow-400' : 'text-gray-600'}`}
        />
      ))}
      {score > 0 && <span className="text-sm text-muted-foreground ml-1">{score}</span>}
    </div>
  );
};

const ChatList = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [ratedConnections, setRatedConnections] = useState(new Set());
  const [ratingForms, setRatingForms] = useState({});

  useEffect(() => {
    loadAllItems();
    const interval = setInterval(loadAllItems, 5000);
    return () => clearInterval(interval);
  }, []);

  const loadAllItems = async () => {
    try {
      const [convResponse, reqResponse] = await Promise.all([
        axios.get('api/chat/conversations/'),
        axios.get('api/lawyer/connections/')
      ]);

      const conversations = (convResponse.data.results || convResponse.data || []).map(c => ({ ...c, type: 'conversation' }));
      const requests = (reqResponse.data || []).map(r => ({ ...r, type: 'request' }));

      const combined = [...conversations, ...requests].sort((a, b) => new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at));
      setItems(combined);

      const accepted = requests.filter(r => r.status === 'accepted');
      const rated = new Set();
      await Promise.all(accepted.map(async (req) => {
        try {
          const res = await axios.get(`api/lawyer/${req.lawyer?.id}/ratings/`);
          const hasRating = (res.data.ratings || []).some(r => r.connection_request === req.id);
          if (hasRating) rated.add(req.id);
        } catch (_) { /* ignore */ }
      }));
      setRatedConnections(rated);
    } catch (err) {
      toast.error(err.response?.data?.error || 'Failed to load messages and requests.');
    } finally {
      setLoading(false);
    }
  };

  const handleWithdraw = async (connectionId) => {
    if (!window.confirm('Are you sure you want to withdraw this request?')) return;
    try {
      await axios.patch(`api/lawyer/connections/${connectionId}/withdraw/`);
      toast.success('Request withdrawn.');
      loadAllItems();
    } catch (err) {
      toast.error(err.response?.data?.error || 'Failed to withdraw request.');
    }
  };

  const handleSubmitRating = async (connectionId) => {
    const form = ratingForms[connectionId] || { score: 0, comment: '' };
    if (!form.score) {
      toast.error('Please select a star rating.');
      return;
    }
    try {
      await axios.post('api/lawyer/ratings/', {
        connection_request_id: connectionId,
        score: form.score,
        comment: form.comment || '',
      });
      toast.success('Rating submitted!');
      setRatedConnections(prev => new Set([...prev, connectionId]));
    } catch (err) {
      toast.error(err.response?.data?.error || 'Failed to submit rating.');
    }
  };

  const openChat = async (connection) => {
    try {
      const convResponse = await axios.get(`api/chat/conversations/?connection_request_id=${connection.id}`);
      if (convResponse.data?.id) {
        navigate(`/chat/${convResponse.data.id}`);
      }
    } catch (err) {
      toast.error(err.response?.data?.error || 'Failed to open chat.');
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto py-10 animate-fade-in">
        <div className="text-center text-gray-400">Loading...</div>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-10 animate-fade-in">
      <div className="text-center mb-10">
        <div className="inline-flex items-center gap-2 mb-3 px-3 py-1 bg-blue-500/10 rounded-full border border-blue-500/20">
          <span className="text-blue-400 text-xs font-medium">Messages & Requests</span>
        </div>
        <h1 className="text-4xl md:text-5xl font-bold text-white mb-3">Your Communications</h1>
        <p className="text-gray-400 max-w-2xl mx-auto">Active chats, connection requests, and ratings.</p>
      </div>

      {items.length === 0 ? (
        <Card className="bg-gray-800/40 backdrop-blur-sm border border-gray-700/50">
          <CardContent className="p-10 text-center">
            <MessageSquare className="w-16 h-16 text-gray-500 mx-auto mb-4" />
            <p className="text-gray-400">No items to show.</p>
            <p className="text-gray-500 text-sm mt-2">Connect with a lawyer to start a conversation.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {items.map((item) => {
            if (item.type === 'conversation') {
              const otherUser = item.client?.id === user?.id ? item.lawyer : item.client;
              return (
                <Card
                  key={`conv-${item.id}`}
                  className="bg-gray-800/40 backdrop-blur-sm border border-gray-700/50 hover:border-gray-600 transition-all duration-200 cursor-pointer"
                  onClick={() => navigate(`/chat/${item.id}`)}
                >
                  <CardContent className="p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3 flex-1">
                      <div className="w-12 h-12 bg-blue-600/20 border border-blue-500/30 rounded-full flex items-center justify-center">
                        <span className="text-blue-400 font-semibold">
                          {otherUser?.name?.split(' ').map(n => n[0]).join('') || otherUser?.username?.slice(0, 2).toUpperCase() || 'U'}
                        </span>
                      </div>
                      <div className="flex-1">
                        <h3 className="text-white font-semibold">{otherUser?.name || otherUser?.username || 'Unknown User'}</h3>
                        <p className="text-gray-400 text-sm truncate">
                          {item.last_message ? item.last_message.message : 'No messages yet'}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      {item.unread_count > 0 && (
                        <span className="bg-blue-600 text-white text-xs font-bold rounded-full w-6 h-6 flex items-center justify-center">
                          {item.unread_count}
                        </span>
                      )}
                      <ArrowRight className="w-5 h-5 text-gray-400" />
                    </div>
                  </CardContent>
                </Card>
              );
            }

            if (item.type === 'request' && item.status === 'pending') {
              const lawyer = item.lawyer;
              return (
                <Card key={`req-${item.id}`} className="bg-gray-800/40 backdrop-blur-sm border border-gray-700/50">
                  <CardContent className="p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3 flex-1">
                      <div className="w-12 h-12 bg-yellow-600/20 border border-yellow-500/30 rounded-full flex items-center justify-center">
                        <Clock className="w-6 h-6 text-yellow-400" />
                      </div>
                      <div className="flex-1">
                        <h3 className="text-white font-semibold">Request to {lawyer?.name || lawyer?.username}</h3>
                        <p className="text-yellow-400 text-sm">Status: {item.status}</p>
                      </div>
                    </div>
                    <Button variant="destructive" size="sm" onClick={() => handleWithdraw(item.id)}>
                      Withdraw
                    </Button>
                  </CardContent>
                </Card>
              );
            }

            if (item.type === 'request' && item.status === 'accepted') {
              const lawyer = item.lawyer;
              const alreadyRated = ratedConnections.has(item.id);
              const form = ratingForms[item.id] || { score: 0, comment: '' };

              return (
                <Card key={`req-acc-${item.id}`} className="bg-gray-800/40 backdrop-blur-sm border border-green-700/30">
                  <CardContent className="p-4 space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-3">
                      <div>
                        <h3 className="text-white font-semibold">Connected with {lawyer?.name || lawyer?.username}</h3>
                        <p className="text-green-400 text-sm">Status: accepted</p>
                      </div>
                      <div className="flex gap-2">
                        {item.meeting_link && (
                          <Button
                            size="sm"
                            className="bg-green-600 hover:bg-green-700"
                            onClick={() => window.open(item.meeting_link, '_blank')}
                          >
                            <Video className="w-4 h-4 mr-1" />
                            Join Meet
                          </Button>
                        )}
                        <Button size="sm" variant="outline" onClick={() => openChat(item)}>
                          Open Chat
                        </Button>
                      </div>
                    </div>

                    {!alreadyRated && user?.role !== 'lawyer' && (
                      <div className="border-t border-gray-700/50 pt-3 space-y-2">
                        <p className="text-sm text-gray-400">Rate your consultation:</p>
                        <StarRatingInput
                          value={form.score}
                          onChange={(score) => setRatingForms(prev => ({ ...prev, [item.id]: { ...form, score } }))}
                        />
                        <Input
                          placeholder="Optional comment..."
                          value={form.comment}
                          onChange={(e) => setRatingForms(prev => ({ ...prev, [item.id]: { ...form, comment: e.target.value } }))}
                          className="bg-gray-700/50 border-gray-600 text-white placeholder-gray-400"
                        />
                        <Button size="sm" onClick={() => handleSubmitRating(item.id)} className="bg-yellow-600 hover:bg-yellow-700">
                          Submit Rating
                        </Button>
                      </div>
                    )}
                    {alreadyRated && (
                      <p className="text-sm text-green-400 flex items-center gap-1">
                        <Star className="w-4 h-4 fill-yellow-400 text-yellow-400" /> Rating submitted
                      </p>
                    )}
                  </CardContent>
                </Card>
              );
            }

            return null;
          })}
        </div>
      )}
    </div>
  );
};

export { StarRatingDisplay };
export default ChatList;
