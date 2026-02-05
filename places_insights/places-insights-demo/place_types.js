// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// This file contains a comprehensive list of place types from the documentation
// to be used by the application's autocomplete feature.

const PLACE_TYPES = [
  'accounting', 'acai_shop', 'administrative_area_level_1', 'administrative_area_level_2', 'administrative_area_level_3', 'administrative_area_level_4', 'administrative_area_level_5', 
  'adult_club', 'advertising_agency', 'afghan_restaurant', 'african_restaurant', 'airport', 'airport_gate', 'airport_lounge', 'airport_terminal', 'airpost', 'airprt_runway', 
  'american_restaurant', 'amphitheater', 'amusement_center', 'amusement_park', 'animal_and_plant_health_inspection_service', 'animal_shelter', 'aquarium', 'archipelago', 
  'art_gallery', 'art_school', 'art_studio', 'ashram', 'asian_restaurant', 'assisted_living_facility', 'athletic_field', 'atm', 'attraction', 'auditorium', 'australian_restaurant', 
  'austrian_restaurant', 'auto_detailing_service', 'auto_parts_store', 'auto_repair_shop', 'badminton_court', 'bagel_shop', 'bakery', 'ballet_school', 'bank', 'banquet_hall', 
  'bar', 'barbecue_restaurant', 'barber_shop', 'baseball_field', 'basketball_court', 'beach', 'beauty_salon', 'bed_and_breakfast', 'belgian_restaurant', 'beverages', 'bicycle_store', 
  'billiards_hall', 'bistro', 'boat_club', 'boat_dealer', 'boat_launch', 'boat_rental', 'boat_tour_agency', 'boating_and_sailing', 'book_store', 'botanical_garden', 'bowling_alley', 
  'brazilian_restaurant', 'breakfast_restaurant', 'brewery', 'british_restaurant', 'brunch_restaurant', 'buddhist_temple', 'buffet_restaurant', 'bungalow', 'burrito_restaurant', 'bus_charter', 
  'bus_station', 'bus_stop', 'business_park', 'butcher_shop', 'cafe', 'cafeteria', 'cajun_restaurant', 'cake_shop', 'californian_restaurant', 'cambodian_restaurant', 'campground', 
  'camping_cabin', 'canadian_restaurant', 'candy_store', 'cannabis_store', 'cape', 'car_dealer', 'car_rental', 'car_repair', 'car_wash', 'caribbean_restaurant', 'carpenter', 
  'casino', 'catering_service', 'cemetery', 'chalet', 'charity', 'charter_school', 'check_cashing_service', 'child_care_agency', 'childrens_club', 'childrens_museum', 'chilean_restaurant', 
  'chinese_restaurant', 'chiropractor', 'chocolate_shop', 'christmas_market', 'church', 'city_hall', 'civic_center', 'classical_music_venue', 'clinic', 'clothing_store', 
  'club', 'cocktail_bar', 'coffee_shop', 'college', 'colombian_restaurant', 'comedy_club', 'community_center', 'community_garden', 'community_hall', 'computer_repair_service', 
  'concert_hall', 'condominium_complex', 'confectionery', 'conference_center', 'convenience_store', 'convention_center', 'cooperative', 'corporate_office', 'cosmetics_store', 'cottage', 
  'country', 'country_club', 'courthouse', 'couture_store', 'coworking_space', 'creek', 'creole_restaurant', 'creperie', 'cricket_ground', 'cultural_center', 'currency_exchange', 'curtain_store', 
  'cycling_park', 'czech_restaurant', 'dance_hall', 'dance_school', 'day_care_center', 'deli', 'dental_clinic', 'dentist', 'department_store', 'dessert_restaurant', 'dessert_shop', 
  'dim_sum_restaurant', 'diner', 'disc_golf_course', 'distillery', 'dive_shop', 'dog_park', 'dominican_restaurant', 'donut_shop', 'door_and_window_store', 'drama_school', 'driving_school', 
  'drugstore', 'dry_cleaner', 'dump_truck_dealer', 'dumpling_restaurant', 'dutch_restaurant', 'eclectic_restaurant', 'ecuadorian_restaurant', 'educational_center', 'egyptian_restaurant', 
  'electric_vehicle_charging_station', 'electrical_equipment_supplier', 'electrician', 'electronics_store', 'elementary_school', 'embassy', 'emergency_room', 'english_restaurant', 'equestrian_club', 
  'eritrean_restaurant', 'ethiopian_restaurant', 'event_venue', 'extended_stay_hotel', 'family_restaurant', 'farm', 'farmers_market', 'fast_food_restaurant', 'ferris_wheel', 'ferry_terminal', 
  'festival', 'filipino_restaurant', 'fine_dining_restaurant', 'finnish_restaurant', 'fire_station', 'fish_and_chips_restaurant', 'fish_store', 'fishing_charter', 'fishing_pond', 'fitness_center', 
  'flea_market', 'florist', 'food_and_drink', 'food_court', 'food_delivery', 'food_pantry', 'food_producer', 'food_truck', 'football_field', 'foot_care', 'forest', 'fraternal_organization', 
  'french_restaurant', 'frozen_yogurt_shop', 'fruit_and_vegetable_store', 'funeral_home', 'furniture_store', 'fusion_restaurant', 'game_store', 'garden', 'gas_station', 'gastropub', 
  'general_contractor', 'geological_feature', 'german_restaurant', 'ghanaian_restaurant', 'gift_shop', 'glass_and_mirror_shop', 'go_kart_track', 'golf_course', 'gourmet_grocery_store', 
  'government_office', 'greek_restaurant', 'grocery_store', 'guatemalan_restaurant', 'guest_house', 'gym', 'gymnastics_center', 'hair_care', 'hair_salon', 'haitian_restaurant', 
  'halal_restaurant', 'hamburger_restaurant', 'handball_court', 'hardware_store', 'hawaiian_restaurant', 'health_and_wellness', 'health_food_store', 'health_spa', 'heliport', 'high_school', 
  'hiking_area', 'hindu_temple', 'historical_landmark', 'historical_place', 'historical_society', 'hockey_rink', 'home_goods_store', 'home_improvement_store', 'honduran_restaurant', 
  'horse_riding_school', 'hospital', 'hostel', 'hot_dog_stand', 'hot_pot_restaurant', 'hotel', 'house', 'household_goods_store', 'housing_complex', 'hungarian_restaurant', 'ice_cream_shop', 
  'ice_skating_rink', 'indian_restaurant', 'indonesian_restaurant', 'indoor_cycling', 'indoor_playground', 'industrial_park', 'inn', 'insurance_agency', 'internet_cafe', 'intersection', 
  'investment_firm', 'irish_pub', 'irish_restaurant', 'island', 'israeli_restaurant', 'italian_restaurant', 'jamaican_restaurant', 'japanese_restaurant', 'jazz_club', 'jewelry_store', 'jewish_restaurant', 
  'judo_school', 'juice_shop', 'karaoke', 'kebab_shop', 'kindergarten', 'korean_restaurant', 'kosher_restaurant', 'labor_union', 'lake', 'landmark', 'language_school', 'laotian_restaurant', 
  'latin_american_restaurant', 'laundromat', 'laundry', 'law_firm', 'lawyer', 'leather_goods_store', 'lebanese_restaurant', 'legal_services', 'leisure_center', 'library', 'light_rail_station', 
  'liquor_store', 'loan_agency', 'locality', 'locksmith', 'lodging', 'lounge', 'luggage_store', 'lunch_restaurant', 'madagascan_restaurant', 'mail_box', 'mailing_service', 'malaysian_restaurant', 
  'marina', 'market', 'marketplace', 'martial_arts_school', 'masonic_temple', 'massage_therapist', 'meal_delivery', 'meal_takeaway', 'medical_clinic', 'medical_lab', 'medical_supply_store', 
  'meditation_center', 'mediterranean_restaurant', 'meeting_room', 'memorial_park', 'mental_health_clinic', 'mexican_restaurant', 'middle_eastern_restaurant', 'military_base', 
  'miniature_golf_course', 'mobile_home_park', 'modern_art_museum', 'modern_european_restaurant', 'mongolian_restaurant', 'monument', 'moroccan_restaurant', 'mosque', 'motel', 'motorcycle_dealer', 
  'motorcycle_rental', 'motorcycle_repair_shop', 'mountain', 'mountain_peak', 'movie_rental', 'movie_theater', 'moving_company', 'museum', 'music_school', 'music_venue', 'nail_salon', 
  'national_forest', 'national_park', 'natural_feature', 'nepalese_restaurant', 'new_zealand_restaurant', 'nicaraguan_restaurant', 'night_club', 'nigerian_restaurant', 'non_profit_organization', 
  'noodle_restaurant', 'nordic_restaurant', 'north_african_restaurant', 'north_indian_restaurant', 'norwegian_restaurant', 'nursing_home', 'observation_deck', 'observatory', 'off_roading_area', 
  'office_supply_store', 'opera_house', 'optician', 'optometrist', 'orthodox_church', 'orthopedic_surgeon', 'orthopedist', 'osteopath', 'outlet_store', 'package_delivery_service', 
  'paella_restaurant', 'pakistani_restaurant', 'pan_asian_restaurant', 'panamanian_restaurant', 'park', 'park_and_ride', 'parking', 'parking_garage', 'parkway', 'party_planner', 'passport_office', 
  'pastry_shop', 'patio', 'pawn_shop', 'pediatrician', 'peninsula', 'pension', 'performing_arts_theater', 'persian_restaurant', 'peruvian_restaurant', 'pet_store', 'pharmacy', 'philharmonic_hall', 
  'phone_repair_shop', 'photographer', 'physical_therapist', 'physician', 'physiotherapist', 'picnic_ground', 'pier', 'pilates_studio', 'pizza_restaurant', 'pizza_takeaway', 'place_of_worship', 
  'planetarium', 'plant_nursery', 'plumber', 'podiatrist', 'point_of_interest', 'police_station', 'polish_restaurant', 'political_organization', 'pond', 'pool_hall', 'port', 'portuguese_restaurant', 
  'post_office', 'poultry_store', 'prefecture', 'preschool', 'primary_school', 'private_guest_room', 'private_school', 'private_tutor', 'produce_market', 'professional_organization', 'psychiatrist', 
  'psychologist', 'psychotherapist', 'pub', 'public_bath', 'public_bathroom', 'public_housing', 'public_school', 'public_transportation', 'puerto_rican_restaurant', 'pumping_station', 'punjabi_restaurant', 
  'quarry', 'race_track', 'racquetball_court', 'ramen_restaurant', 'ranch', 'rapid_transit_station', 'real_estate_agency', 'recreation_center', 'recycling_center', 'redevelopment_agency', 
  'reggae_night_club', 'regional_park', 'rehabilitation_center', 'religious_organization', 'rental_agency', 'repair_service', 'research_institute', 'reservable', 'reservoir', 'resort', 'resort_hotel', 
  'restaurant', 'rest_stop', 'retirement_home', 'river', 'road', 'rock_climbing_gym', 'roller_coaster', 'roller_skating_rink', 'romanian_restaurant', 'roofing_contractor', 'rooming_house', 
  'route', 'rv_park', 'sailing_club', 'salad_shop', 'salon', 'salsa_club', 'salvadoran_restaurant', 'sandwich_shop', 'sauna', 'savannah', 'school', 'school_district_office', 'science_museum', 
  'scottish_restaurant', 'scuba_diving_center', 'sculpture', 'seafood_restaurant', 'secondary_school', 'self_storage_facility', 'senior_center', 'serbian_restaurant', 'service_station', 
  'sex_therapist', 'shabu_shabu_restaurant', 'shawarma_restaurant', 'shipping_and_mailing_service', 'shoe_store', 'shopping_mall', 'shooting_range', 'shrine', 'sichuan_restaurant', 'sicilian_restaurant', 
  'singaporean_restaurant', 'skate_park', 'skateboard_shop', 'skating_rink', 'ski_resort', 'skin_care_clinic', 'skydiving_center', 'slovak_restaurant', 'slovenian_restaurant', 'smoothie_shop', 
  'snack_bar', 'soccer_field', 'social_club', 'social_security_office', 'social_service_organization', 'softball_field', 'soul_food_restaurant', 'soup_restaurant', 'south_african_restaurant', 
  'south_indian_restaurant', 'south_pacific_restaurant', 'south_american_restaurant', 'southeast_asian_restaurant', 'southwestern_restaurant', 'souvenir_store', 'spa', 'spanish_restaurant', 
  'special_education_school', 'sports_bar', 'sports_club', 'sports_complex', 'sporting_goods_store', 'squash_court', 'stadium', 'stable', 'state_park', 'steak_house', 'storage', 'store', 
  'street', 'strip_club', 'student_housing', 'studio', 'subway_station', 'sushi_restaurant', 'swamp', 'swedish_restaurant', 'swimming_pool', 'swim_club', 'swiss_restaurant', 'synagogue', 
  'syrian_restaurant', 'taco_restaurant', 'taiwanese_restaurant', 'takeout', 'tanning_salon', 'tapas_restaurant', 'tasting_room', 'tattoo_shop', 'tax_assessor', 'tax_consultant', 'tax_department', 
  'taxi_stand', 'tea_house', 'tea_room', 'technical_school', 'telecommunications_service_provider', 'telemarketing_service', 'temple', 'tennis_court', 'tennis_club', 'teppanyaki_restaurant', 
  'thai_restaurant', 'theatre', 'theme_park', 'therapist', 'tibetan_restaurant', 'ticket_outlet', 'tiki_bar', 'tire_shop', 'title_company', 'tobacco_shop', 'tongolese_restaurant', 'tourist_attraction', 
  'tour_agency', 'townhouse_complex', 'town_hall', 'trade_school', 'traditional_music_venue', 'trail', 'trailer_dealer', 'train_station', 'transit_depot', 'transit_station', 'translation_service', 
  'transportation', 'travel_agency', 'truck_stop', 'trinidadian_restaurant', 'turkish_restaurant', 'tuscan_restaurant', 'udon_restaurant', 'ukrainian_restaurant', 'unagi_restaurant', 'university', 
  'uruguayan_restaurant', 'used_car_dealer', 'uyghur_restaurant', 'uzbek_restaurant', 'variety_store', 'vegan_restaurant', 'vegetarian_restaurant', 'vehicle_inspection', 'venetian_restaurant', 
  'venezuelan_restaurant', 'veterans_affairs', 'veterinarian', 'video_arcade', 'video_game_store', 'video_production_service', 'vietnamese_restaurant', 'villa', 'village_hall', 'vineyard', 
  'visitor_center', 'volcano', 'volleyball_court', 'warehouse_store', 'waste_management_service', 'watch_repair_service', 'waterfall', 'water_park', 'water_skiing_club', 'water_sports_equipment_rental', 
  'waxing_salon', 'wedding_planner', 'wedding_venue', 'welsh_restaurant', 'western_restaurant', 'wharf', 'wholesale_club', 'wholesaler', 'wifi_hotspot', 'wildlife_park', 'wildlife_refuge', 'wine_bar', 
  'winery', 'womens_health_clinic', 'yakitori_restaurant', 'yoga_studio', 'youth_organization', 'zoo'
];