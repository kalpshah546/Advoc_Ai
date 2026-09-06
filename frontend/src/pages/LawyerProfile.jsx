import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { User, Mail, Phone, GraduationCap, Building, Clock, DollarSign, Star } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/Components/ui/Card";
import { Label } from "@/Components/ui/Label";
import axios from "../api/axios";
import toast from "react-hot-toast";
import { Button } from "@/Components/ui/button";
import { useAuth } from "../context/AuthContext";
import ConnectModal from "../Components/ConnectModal";

const LawyerProfile = () => {
  const { id } = useParams();
  const { user } = useAuth();
  const [profileData, setProfileData] = useState(null);
  const [ratingsData, setRatingsData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const [profileRes, ratingsRes] = await Promise.all([
          axios.get(`api/lawyer/${id}/`),
          axios.get(`api/lawyer/${id}/ratings/`),
        ]);
        setProfileData(profileRes.data);
        setRatingsData(ratingsRes.data);
      } catch (err) {
        console.error("Failed to load lawyer profile:", err);
        toast.error(err.response?.data?.error || "Unable to load lawyer profile.");
      } finally {
        setLoading(false);
      }
    };

    if (id) {
      fetchProfile();
    }
  }, [id]);

  const openConnectModal = () => {
    setIsModalOpen(true);
  };

  const handleConnect = async ({ message, preferredTime }) => {
    if (!profileData?.user?.id) return;

    if (!preferredTime) { // message is now optional
      toast.error('Please provide a preferred time.');
      return;
    }

    let preferredTimeIso = null;
    if (preferredTime) {
      const parsedDate = new Date(preferredTime);
      if (Number.isNaN(parsedDate.getTime())) {
        toast.error("Please provide a valid consultation time.");
        return;
      }
      preferredTimeIso = parsedDate.toISOString();
    }

    try {
      const payload = {
        message: message || "",
        preferred_time: preferredTimeIso,
      };
      console.log("DEBUG: Sending connection request payload:", payload); // New debug log
      const response = await axios.post(`api/lawyer/${profileData.user.id}/connect/`, payload);
      if (response.data.message) {
        toast.success(response.data.message);
      } else {
        toast.success('Connection request sent!');
      }
    } catch (err) {
      console.error("Failed to connect with lawyer:", err);
      toast.error(err.response?.data?.error || "Unable to send connection request.");
    } finally {
      setIsModalOpen(false);
    }
  };

  const getInitials = (name) => {
    if (!name) return '';
    return name.split(' ').map(n => n[0]).join('').toUpperCase();
  };

  if (loading) {
    return (
      <div className="container mx-auto py-10 animate-fade-in">
        <div className="text-center text-gray-400">Loading lawyer profile...</div>
      </div>
    );
  }

  if (!profileData) {
    return (
      <div className="container mx-auto py-10 animate-fade-in">
        <div className="text-center text-red-400">Lawyer profile not found.</div>
      </div>
    );
  }

  const { user: lawyerUser } = profileData;
  const experienceYears = profileData.experience_years ?? 0;

  const ProfileDisplayField = ({ icon, label, value }) => (
    <div className="flex items-center gap-4 p-3 bg-gray-800/30 rounded-lg border border-gray-700/50 hover:border-gray-600 transition-all duration-200 group">
      <div className="w-10 h-10 bg-blue-600/20 rounded-lg flex items-center justify-center text-blue-400 group-hover:bg-blue-600/30 transition-colors duration-200">
        {icon}
      </div>
      <div className="flex-1">
        <Label className="text-gray-400 text-xs">{label}</Label>
        <p className="text-white text-sm font-medium group-hover:text-blue-400 transition-colors duration-200">{value}</p>
      </div>
    </div>
  );

  return (
    <>
      <div className="container mx-auto py-10 animate-fade-in">
        <Card className="max-w-3xl mx-auto bg-gray-800/40 backdrop-blur-sm border border-gray-700/50">
          <CardHeader className="text-center">
            <div className="inline-flex items-center gap-2 mb-3 px-3 py-1 bg-blue-500/10 rounded-full border border-blue-500/20">
              <span className="text-blue-400 text-xs font-medium">
                Lawyer Profile · {profileData.verification_status?.toUpperCase()}
              </span>
            </div>
            <div className="w-24 h-24 bg-blue-600/20 text-blue-400 rounded-full flex items-center justify-center text-2xl font-bold mx-auto mb-4 border-2 border-blue-500/30">
              {getInitials(lawyerUser?.name || lawyerUser?.username || '')}
            </div>
            <CardTitle className="text-2xl font-bold text-white mb-1">
              {lawyerUser?.name || lawyerUser?.username}
            </CardTitle>
            <CardDescription className="text-gray-400">
              {profileData.education || profileData.specializations?.join(', ') || 'Legal Professional'}
            </CardDescription>
            {ratingsData && ratingsData.total_ratings > 0 && (
              <div className="flex items-center justify-center gap-2 mt-3">
                <div className="flex gap-0.5">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <Star
                      key={star}
                      className={`w-5 h-5 ${star <= Math.round(ratingsData.average_score) ? 'text-yellow-400 fill-yellow-400' : 'text-gray-600'}`}
                    />
                  ))}
                </div>
                <span className="text-yellow-400 font-semibold">{ratingsData.average_score}</span>
                <span className="text-gray-500 text-sm">({ratingsData.total_ratings} reviews)</span>
              </div>
            )}
            <div className="mt-4 flex justify-center">
              <Button onClick={openConnectModal} className="bg-blue-600 hover:bg-blue-700 text-white">
                Connect with {lawyerUser?.name || 'Lawyer'}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-8">
            <div className="space-y-6">
              <h2 className="text-2xl font-bold text-white border-b border-gray-700 pb-3 flex items-center">
                <span className="w-1 h-8 bg-blue-500 rounded-full mr-3"></span>
                Personal Information
              </h2>
              <ProfileDisplayField
                icon={<User className="w-5 h-5" />}
                label="Full Name"
                value={lawyerUser?.name || 'Not provided'}
              />
              <ProfileDisplayField
                icon={<User className="w-5 h-5" />}
                label="User Name"
                value={lawyerUser?.username || 'Not provided'}
              />
              <ProfileDisplayField
                icon={<Mail className="w-5 h-5" />}
                label="Email"
                value={lawyerUser?.email || 'Not available'}
              />
              <ProfileDisplayField
                icon={<Phone className="w-5 h-5" />}
                label="Phone"
                value={profileData.phone || lawyerUser?.phone || 'Not provided'}
              />
            </div>

            <div className="space-y-6">
              <h2 className="text-2xl font-bold text-white border-b border-gray-700 pb-3 flex items-center">
                <span className="w-1 h-8 bg-blue-500 rounded-full mr-3"></span>
                Professional Details
              </h2>
              <ProfileDisplayField
                icon={<GraduationCap className="w-5 h-5" />}
                label="Education"
                value={profileData.education || 'Not provided'}
              />
              <ProfileDisplayField
                icon={<Building className="w-5 h-5" />}
                label="Law Firm"
                value={profileData.law_firm || 'Independent'}
              />
              <ProfileDisplayField
                icon={<Clock className="w-5 h-5" />}
                label="Experience"
                value={`${experienceYears} ${experienceYears === 1 ? 'year' : 'years'}`}
              />
              <ProfileDisplayField
                icon={<DollarSign className="w-5 h-5" />}
                label="Consultation Fee"
                value={profileData.consultation_fee || 'Contact for details'}
              />
              {profileData.bio && (
                <div className="flex flex-col gap-2 p-3 bg-gray-800/30 rounded-lg border border-gray-700/50">
                  <Label className="text-gray-400 text-xs">About</Label>
                  <p className="text-white text-sm leading-relaxed whitespace-pre-line">
                    {profileData.bio}
                  </p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
      {profileData && (
        <ConnectModal
          isOpen={isModalOpen}
          onOpenChange={setIsModalOpen}
          lawyer={profileData}
          onConnect={handleConnect}
        />
      )}
    </>
  );
};

export default LawyerProfile;
