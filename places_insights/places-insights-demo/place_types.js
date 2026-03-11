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
  'acai_shop', 'academic_department', 'accounting', 'adventure_sports_center', 'afghani_restaurant', 'african_restaurant', 'aircraft_rental_service', 
  'airport', 'airstrip', 'american_restaurant', 'amphitheatre', 'amusement_center', 'amusement_park', 'apartment_building', 'apartment_complex', 
  'aquarium', 'arena', 'argentinian_restaurant', 'art_gallery', 'art_museum', 'art_studio', 'asian_fusion_restaurant', 'asian_grocery_store', 
  'asian_restaurant', 'association_or_organization', 'astrologer', 'athletic_field', 'atm', 'auditorium', 'australian_restaurant', 
  'austrian_restaurant', 'auto_parts_store', 'bagel_shop', 'bakery', 'bangladeshi_restaurant', 'bank', 'banquet_hall', 'bar', 'bar_and_grill', 
  'barbecue_area', 'barbecue_restaurant', 'barber_shop', 'basque_restaurant', 'bavarian_restaurant', 'beach', 'beautician', 'beauty_salon', 
  'bed_and_breakfast', 'beer_garden', 'belgian_restaurant', 'bicycle_store', 'bike_sharing_station', 'bistro', 'body_art_service', 'book_store', 
  'botanical_garden', 'bowling_alley', 'brazilian_restaurant', 'breakfast_restaurant', 'brewery', 'brewpub', 'bridge', 'british_restaurant', 
  'brunch_restaurant', 'buddhist_temple', 'budget_japanese_inn', 'buffet_restaurant', 'building_materials_store', 'burmese_restaurant', 
  'burrito_restaurant', 'business_center', 'butcher_shop', 'cafe', 'cafeteria', 'cajun_restaurant', 'cake_shop', 'californian_restaurant', 
  'cambodian_restaurant', 'campground', 'camping_cabin', 'candy_store', 'cantonese_restaurant', 'car_dealer', 'car_rental', 'car_repair', 
  'car_wash', 'caribbean_restaurant', 'casino', 'castle', 'cat_cafe', 'catering_service', 'cell_phone_store', 'cemetery', 'chauffeur_service', 
  'chicken_restaurant', 'chicken_wings_restaurant', 'child_care_agency', 'childrens_camp', 'chilean_restaurant', 'chinese_noodle_restaurant', 
  'chinese_restaurant', 'chiropractor', 'chocolate_factory', 'chocolate_shop', 'church', 'city_hall', 'city_park', 'clothing_store', 
  'cocktail_bar', 'coffee_roastery', 'coffee_shop', 'coffee_stand', 'colombian_restaurant', 'comedy_club', 'community_center', 'concert_hall', 
  'condominium_complex', 'confectionery', 'consultant', 'convenience_store', 'convention_center', 'corporate_office', 'cosmetics_store', 
  'cottage', 'courier_service', 'courthouse', 'coworking_space', 'croatian_restaurant', 'cuban_restaurant', 'cultural_center', 
  'cultural_landmark', 'cycling_park', 'czech_restaurant', 'dance_hall', 'danish_restaurant', 'deli', 'dental_clinic', 'dentist', 
  'department_store', 'dessert_restaurant', 'dessert_shop', 'dim_sum_restaurant', 'diner', 'discount_store', 'discount_supermarket', 
  'doctor', 'dog_cafe', 'dog_park', 'donut_shop', 'drugstore', 'dumpling_restaurant', 'dutch_restaurant', 'eastern_european_restaurant', 
  'ebike_charging_station', 'educational_institution', 'electric_vehicle_charging_station', 'electrician', 'electronics_store', 'embassy', 
  'employment_agency', 'establishment', 'ethiopian_restaurant', 'european_restaurant', 'event_venue', 'extended_stay_hotel', 'falafel_restaurant', 
  'family_restaurant', 'farmers_market', 'farm', 'farmstay', 'fast_food_restaurant', 'ferris_wheel', 'ferry_service', 'ferry_terminal', 
  'filipino_restaurant', 'finance', 'fine_dining_restaurant', 'fire_station', 'fish_and_chips_restaurant', 'fishing_charter', 'fishing_pier', 
  'fishing_pond', 'fitness_center', 'flea_market', 'florist', 'fondue_restaurant', 'food', 'food_court', 'food_delivery', 'food_store', 
  'foot_care', 'fountain', 'french_restaurant', 'funeral_home', 'furniture_store', 'fusion_restaurant', 'garden', 'garden_center', 
  'gas_station', 'gastropub', 'general_contractor', 'general_hospital', 'general_store', 'german_restaurant', 'gift_shop', 'go_karting_venue', 
  'golf_course', 'government_office', 'greek_restaurant', 'grocery_store', 'guest_house', 'gym', 'gyro_restaurant', 'hair_care', 'hair_salon', 
  'halal_restaurant', 'hamburger_restaurant', 'hardware_store', 'hawaiian_restaurant', 'health', 'health_food_store', 'heliport', 'hiking_area', 
  'hindu_temple', 'historical_landmark', 'historical_place', 'history_museum', 'home_goods_store', 'home_improvement_store', 'hookah_bar', 
  'hospital', 'hostel', 'hot_dog_restaurant', 'hot_dog_stand', 'hot_pot_restaurant', 'hotel', 'housing_complex', 'hungarian_restaurant', 
  'hypermarket', 'ice_cream_shop', 'ice_skating_rink', 'indian_restaurant', 'indoor_golf_course', 'indoor_playground', 'indonesian_restaurant', 
  'inn', 'insurance_agency', 'international_airport', 'internet_cafe', 'irish_pub', 'irish_restaurant', 'island', 'israeli_restaurant', 
  'italian_restaurant', 'japanese_curry_restaurant', 'japanese_inn', 'japanese_izakaya_restaurant', 'japanese_restaurant', 'jewelry_store', 
  'juice_shop', 'karaoke', 'kebab_shop', 'korean_barbecue_restaurant', 'korean_restaurant', 'lake', 'landmark', 'latin_american_restaurant', 
  'laundry', 'lawyer', 'lebanese_restaurant', 'library', 'light_rail_station', 'liquor_store', 'live_music_venue', 'local_government_office', 
  'locksmith', 'lodging', 'lounge_bar', 'makeup_artist', 'malaysian_restaurant', 'manufacturer', 'marina', 'market', 'marketing_consultant', 
  'massage', 'massage_spa', 'meal_delivery', 'meal_takeaway', 'medical_center', 'medical_clinic', 'medical_lab', 'mediterranean_restaurant', 
  'mexican_restaurant', 'middle_eastern_restaurant', 'miniature_golf_course', 'mobile_home_park', 'mongolian_barbecue_restaurant', 'monument', 
  'moroccan_restaurant', 'mosque', 'motel', 'mountain_peak', 'movie_rental', 'movie_theater', 'moving_company', 'museum', 'nail_salon', 
  'national_park', 'natural_feature', 'nature_preserve', 'night_club', 'non_profit_organization', 'noodle_shop', 
  'north_indian_restaurant', 'observation_deck', 'off_roading_area', 'opera_house', 'oyster_bar_restaurant', 'paintball_center', 'painter', 
  'pakistani_restaurant', 'park', 'park_and_ride', 'parking', 'parking_garage', 'parking_lot', 'pastry_shop', 'performing_arts_theater', 
  'persian_restaurant', 'peruvian_restaurant', 'pet_boarding_service', 'pet_care', 'pet_store', 'pharmacy', 'philharmonic_hall', 
  'physiotherapist', 'picnic_ground', 'pizza_delivery', 'pizza_restaurant', 'place_of_worship', 'planetarium', 'playground', 'plaza', 
  'plumber', 'point_of_interest', 'police', 'polish_restaurant', 'portuguese_restaurant', 'post_office', 'premise', 'preschool', 
  'primary_school', 'private_guest_room', 'psychic', 'pub', 'public_bath', 'public_bathroom', 'race_course', 'ramen_restaurant', 'ranch', 
  'real_estate_agency', 'research_institute', 'resort_hotel', 'restaurant', 'rest_stop', 'river', 'roller_coaster', 'romanian_restaurant', 
  'roofing_contractor', 'russian_restaurant', 'rv_park', 'salad_shop', 'sandwich_shop', 'sauna', 'scandinavian_restaurant', 'scenic_spot', 
  'school', 'sculpture', 'seafood_restaurant', 'secondary_school', 'service', 'shawarma_restaurant', 'shipping_service', 'shinto_shrine', 
  'shoe_store', 'shopping_mall', 'skin_care_clinic', 'ski_resort', 'skateboard_park', 'snack_bar', 'soul_food_restaurant', 'soup_restaurant', 
  'south_american_restaurant', 'south_indian_restaurant', 'southwestern_us_restaurant', 'spa', 'spanish_restaurant', 'sporting_goods_store', 
  'sports_activity_location', 'sports_bar', 'sports_club', 'sports_coaching', 'sports_complex', 'sports_school', 'sportswear_store', 
  'sri_lankan_restaurant', 'stable', 'stadium', 'state_park', 'steak_house', 'storage', 'store', 'street_address', 'subpremise', 'subway_station', 
  'summer_camp_organizer', 'supermarket', 'supplier', 'sushi_restaurant', 'swimming_pool', 'swiss_restaurant', 'synagogue', 'taco_restaurant', 
  'tailor', 'taiwanese_restaurant', 'tanning_studio', 'tapas_restaurant', 'taxi_service', 'taxi_stand', 'tea_house', 'tea_store', 
  'telecommunications_service_provider', 'television_studio', 'tennis_court', 'tex_mex_restaurant', 'thai_restaurant', 'thrift_store', 
  'tibetan_restaurant', 'tire_shop', 'toll_station', 'tonkatsu_restaurant', 'tour_agency', 'tourist_attraction', 'tourist_information_center', 
  'toy_store', 'train_station', 'train_ticket_office', 'tram_stop', 'transit_depot', 'transit_station', 'transit_stop', 'transportation_service', 
  'travel_agency', 'truck_dealer', 'truck_stop', 'turkish_restaurant', 'ukrainian_restaurant', 'university', 'vegan_restaurant', 
  'vegetarian_restaurant', 'veterinary_care', 'video_arcade', 'vietnamese_restaurant', 'vineyard', 'visitor_center', 'warehouse_store', 
  'water_park', 'wedding_venue', 'wellness_center', 'western_restaurant', 'wholesaler', 'wildlife_park', 'wildlife_refuge', 'wine_bar', 
  'winery', 'womens_clothing_store', 'woods', 'yakiniku_restaurant', 'yakitori_restaurant', 'yoga_studio', 'zoo'
];