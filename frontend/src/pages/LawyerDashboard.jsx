import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "../api/axios";
import toast from "react-hot-toast";
import { useAuth } from "../context/AuthContext";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/Components/ui/Card";
import { Button } from "@/Components/ui/button";
import { BadgeCheck, Clock, ShieldAlert, MessageSquare, Star, Video } from "lucide-react";

const statusColors = {
  pending: "text-yellow-400",
  approved: "text-green-400",
  rejected: "text-red-400",
};

const formatDateTime = (value) => {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const LawyerDashboard = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [dashboard, setDashboard] = useState(null);
  const [ratingsData, setRatingsData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!user) return;
    if (user.role !== "lawyer") {
      toast.error("This dashboard is only available to lawyer accounts.");
      navigate("/");
      return;
    }

    const loadDashboard = async () => {
      try {
        const response = await axios.get("api/lawyer/dashboard/");
        setDashboard(response.data);
        const lawyerId = response.data.user?.id;
        if (lawyerId) {
          const ratingsRes = await axios.get(`api/lawyer/${lawyerId}/ratings/`);
          setRatingsData(ratingsRes.data);
        }
      } catch (err) {
        console.error("Failed to load lawyer dashboard:", err);
        setError(err.response?.data?.error || "Unable to load lawyer dashboard.");
      } finally {
        setLoading(false);
      }
    };

    loadDashboard();
  }, [user, navigate]);

  const handleConnectionUpdate = async (requestId, status) => {
    try {
      const response = await axios.patch(`api/lawyer/connections/${requestId}/`, { status });
      toast.success(response.data?.message || "Connection updated.");
      
      // Reload dashboard to get updated data including new chat conversations
      const dashboardResponse = await axios.get("api/lawyer/dashboard/");
      setDashboard(dashboardResponse.data);
      const lawyerId = dashboardResponse.data.user?.id;
      if (lawyerId) {
        const ratingsRes = await axios.get(`api/lawyer/${lawyerId}/ratings/`);
        setRatingsData(ratingsRes.data);
      }
      
      // If accepted, show option to open chat
      if (status === 'accepted') {
        setTimeout(() => {
          toast.success('Connection accepted! You can now chat with the client.', { duration: 4000 });
        }, 500);
      }
    } catch (err) {
      console.error("Failed to update connection request:", err);
      toast.error(err.response?.data?.error || "Unable to update request.");
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto py-10 animate-fade-in">
        <div className="text-center text-gray-400">Loading dashboard...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto py-10 animate-fade-in">
        <div className="text-center text-red-400">{error}</div>
      </div>
    );
  }

  if (!dashboard) {
    return null;
  }

  const { profile, connections, summary, user: lawyerUser } = dashboard;
  const verificationStatus = lawyerUser?.lawyer_verification_status || profile?.verification_status || "pending";

  return (
    <div className="container mx-auto py-10 animate-fade-in space-y-8">
      <Card className="bg-card border-border backdrop-blur-sm">
        <CardHeader>
          <div className="flex items-center gap-3">
            <BadgeCheck className="w-10 h-10 text-blue-400" />
            <div>
              <CardTitle className="text-2xl text-white">Lawyer Verification</CardTitle>
              <CardDescription className="text-gray-400">
                Track the status of your professional account verification.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <p className={`text-lg font-semibold ${statusColors[verificationStatus] || "text-gray-300"}`}>
                Status: {verificationStatus.toUpperCase()}
              </p>
              {profile?.verification_notes && (
                <p className="text-sm text-gray-300 mt-2">Notes: {profile.verification_notes}</p>
              )}
            </div>
            {verificationStatus === "pending" && (
              <div className="flex items-center gap-2 text-yellow-300 text-sm">
                <Clock className="w-4 h-4" />
                Your verification is being reviewed. This usually takes 1-2 business days.
              </div>
            )}
            {verificationStatus === "rejected" && (
              <div className="flex items-center gap-2 text-red-300 text-sm">
                <ShieldAlert className="w-4 h-4" />
                Update your credentials or contact support for assistance.
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {ratingsData && (
        <Card className="bg-card border-border">
          <CardContent className="p-5 flex items-center gap-4">
            <Star className="w-8 h-8 text-yellow-400" />
            <div>
              <p className="text-muted-foreground text-sm">Your Rating</p>
              <div className="flex items-center gap-2">
                <div className="flex gap-0.5">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <Star
                      key={star}
                      className={`w-4 h-4 ${star <= Math.round(ratingsData.average_score) ? 'text-yellow-400 fill-yellow-400' : 'text-gray-600'}`}
                    />
                  ))}
                </div>
                <p className="text-2xl font-bold text-foreground">
                  {ratingsData.total_ratings > 0 ? ratingsData.average_score : '—'}
                </p>
                <p className="text-sm text-muted-foreground">({ratingsData.total_ratings} reviews)</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card className="bg-card border-border">
          <CardContent className="p-5">
            <p className="text-muted-foreground text-sm">Total Requests</p>
            <p className="text-2xl font-bold text-foreground">{summary.total_requests}</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="p-5">
            <p className="text-muted-foreground text-sm">Pending</p>
            <p className="text-2xl font-bold text-yellow-300">{summary.pending_requests}</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="p-5">
            <p className="text-muted-foreground text-sm">Accepted</p>
            <p className="text-2xl font-bold text-green-300">{summary.accepted_requests}</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="p-5">
            <p className="text-muted-foreground text-sm">Declined</p>
            <p className="text-2xl font-bold text-red-300">{summary.declined_requests}</p>
          </CardContent>
        </Card>
      </div>

      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground text-xl">Connection Requests</CardTitle>
          <CardDescription className="text-muted-foreground">
            Respond to clients who want to connect with you.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {connections.length === 0 && (
            <div className="text-center text-muted-foreground py-6">No connection requests yet.</div>
          )}
          {connections.map((connection) => (
            <div
              key={connection.id}
              className="border-border rounded-lg p-4 bg-background/30 flex flex-col md:flex-row md:items-center md:justify-between gap-4"
            >
              <div>
                <p className="text-foreground font-semibold">
                  {connection.client?.name || connection.client?.username || "Client"}
                </p>
                <p className="text-sm text-muted-foreground">
                  Contact: {connection.preferred_contact_value || connection.client?.email || "Not provided"}
                </p>
                {connection.preferred_time && (
                  <p className="text-sm text-muted-foreground mt-1">
                    Preferred time: {formatDateTime(connection.preferred_time)}
                  </p>
                )}
                {connection.message && (
                  <p className="text-sm text-foreground mt-2 whitespace-pre-wrap">
                    “{connection.message}”
                  </p>
                )}
                <p className="text-xs text-muted-foreground/80 mt-2">
                  Status: <span className="uppercase">{connection.status}</span>
                </p>
              </div>
              {connection.status === "pending" && (
                <div className="flex gap-2">
                  <Button
                    className="bg-primary hover:bg-primary/90 text-primary-foreground"
                    onClick={() => handleConnectionUpdate(connection.id, "accepted")}
                  >
                    Accept
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => handleConnectionUpdate(connection.id, "declined")}
                  >
                    Decline
                  </Button>
                </div>
              )}
              {connection.status === "accepted" && (
                <div className="flex gap-2 flex-wrap">
                  {(connection.meet_link || connection.meeting_link) && (
                    <Button
                      className="bg-green-600 hover:bg-green-700 text-white"
                      onClick={() => window.open(connection.meet_link || connection.meeting_link, '_blank')}
                    >
                      <Video className="w-4 h-4 mr-2" />
                      Join Meet
                    </Button>
                  )}
                  <Button
                  className="bg-blue-600 hover:bg-blue-700 text-white"
                  onClick={async () => {
                    try {
                      console.log('Opening chat for connection:', connection.id);
                      
                      // Try to get conversation by connection_request_id
                      const convResponse = await axios.get(
                        `api/chat/conversations/?connection_request_id=${connection.id}`
                      );
                      
                      console.log('Conversation response:', convResponse.data);
                      
                      if (convResponse.data && convResponse.data.id) {
                        navigate(`/chat/${convResponse.data.id}`);
                        return;
                      }
                      
                      // Fallback: search all conversations
                      console.log('Fallback: searching all conversations');
                      const allConvsResponse = await axios.get('api/chat/conversations/');
                      const allConvs = allConvsResponse.data.results || allConvsResponse.data || [];
                      const conv = allConvs.find(c => {
                        const matchesConnectionId = c.connection_request_id === connection.id;
                        const matchesUsers = c.client?.id === connection.client?.id && 
                                           c.lawyer?.id === connection.lawyer?.id;
                        return matchesConnectionId || matchesUsers;
                      });
                      
                      if (conv) {
                        console.log('Found conversation:', conv.id);
                        navigate(`/chat/${conv.id}`);
                      } else {
                        console.error('No conversation found for connection:', connection.id);
                        toast.error('Chat conversation not found. Please refresh the page and try again.');
                      }
                    } catch (err) {
                      console.error('Failed to load conversation:', err);
                      console.error('Error details:', err.response?.data);
                      const errorMsg = err.response?.data?.error || err.message || 'Failed to open chat';
                      toast.error(errorMsg);
                    }
                  }}
                >
                  <MessageSquare className="w-4 h-4 mr-2" />
                  Open Chat
                </Button>
                </div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
};

export default LawyerDashboard;

