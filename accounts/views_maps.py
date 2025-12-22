# accounts/views_maps.py
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.core.cache import cache
from django.utils.decorators import method_decorator
import json
import requests
import hashlib
from django.views import View
from decimal import Decimal, InvalidOperation
from .models import CustomUser, CustomerLocation, ISPZone
from billing.models import Subscription
import logging

logger = logging.getLogger(__name__)


# Helper function to determine pin color
def get_pin_color(user, subscription):
    """Determine pin color based on user status"""
    try:
        # If no location or unverified
        if not getattr(user, 'latitude') or not getattr(user, 'longitude'):
            return '#9CA3AF'  # Gray - No location
        
        if not getattr(user, 'location_verified', False):
            return '#FBBF24'  # Yellow - Unverified
        
        # Check if user is active customer
        if not getattr(user, 'is_active_customer', False):
            return '#DC2626'  # Red - Inactive customer
        
        # Check subscription status
        if subscription and subscription.is_active:
            days_remaining = getattr(subscription, 'days_remaining', 0)
            
            # Check if subscription is currently active (between start and end dates)
            now = timezone.now()
            is_currently_active = (
                subscription.start_date <= now <= subscription.end_date
            )
            
            if not is_currently_active:
                return '#DC2626'  # Red - Subscription not active
            
            # Determine color based on days remaining and online status
            if days_remaining <= 0:
                return '#EF4444'  # Red - Expired
            elif days_remaining <= 3:
                return '#F97316'  # Orange - Expiring soon (≤3 days)
            elif days_remaining <= 7:
                return '#EAB308'  # Yellow - Expiring (≤7 days)
            else:
                # Check online status - THIS IS THE KEY PART
                try:
                    from router_manager.models import Device, Router
                    
                    # Check if user has any router
                    user_router = Router.objects.filter(user=user).first()
                    
                    if user_router:
                        # Check if router is online
                        if user_router.is_online:
                            return '#10B981'  # Green - Online and active
                        else:
                            # Check if any devices are online (backup check)
                            online_devices = Device.objects.filter(router=user_router, is_online=True).count()
                            if online_devices > 0:
                                return '#10B981'  # Green - Online via devices
                            else:
                                return '#3B82F6'  # Blue - Offline but active subscription
                    else:
                        # No router assigned yet
                        return '#8B5CF6'  # Purple - No router assigned
                        
                except (ImportError, Exception) as e:
                    print(f"Error checking online status for {user.username}: {e}")
                    return '#3B82F6'  # Blue - Default if Device model not available
        else:
            return '#8B5CF6'  # Purple - No subscription
    
    except Exception as e:
        print(f"Error in get_pin_color for user {user.username}: {e}")
        return '#6B7280'  # Default gray
    

@login_required
def customer_map(request):
    """Customer view: Set and view their location"""
    user = request.user  # CustomUser is the customer
    
    # Get user's active subscription
    subscription = Subscription.objects.filter(
        user=user,
        is_active=True
    ).first()
    
    # Get primary location
    primary_location = CustomerLocation.objects.filter(
        customer=user,
        is_primary=True
    ).first()
    
    context = {
        'user': user,
        'subscription': subscription,
        'primary_location': primary_location,
        'page_title': 'My Location',
        'page_subtitle': 'Set your location for better service',
    }
    
    return render(request, 'accounts/customer_map.html', context)


@login_required
def isp_customer_map(request):
    """ISP view: See all customers on map"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get ISP zones
    zones = ISPZone.objects.filter(tenant=tenant, is_active=True)
    
    # Get statistics
    total_customers = CustomUser.objects.filter(tenant=tenant, role='customer').count()
    
    # Count customers with location data
    customers_with_location = CustomUser.objects.filter(
        tenant=tenant, 
        role='customer'
    ).exclude(
        latitude__isnull=True,
        longitude__isnull=True
    ).count()
    
    context = {
        'tenant': tenant,
        'zones': zones,
        'total_customers': total_customers,
        'customers_with_location': customers_with_location,
        'page_title': 'Customer Map',
        'page_subtitle': 'View customer locations and status',
    }
    
    return render(request, 'accounts/isp_customer_map.html', context)


@login_required
@require_http_methods(['POST'])
def save_customer_location(request):
    """Save customer location from map"""
    try:
        data = json.loads(request.body)
        
        # Validate and parse coordinates
        latitude_str = data.get('latitude')
        longitude_str = data.get('longitude')
        address = data.get('address', '')
        
        if not latitude_str or not longitude_str:
            return JsonResponse({'success': False, 'error': 'Invalid coordinates'})
        
        try:
            latitude = Decimal(str(latitude_str))
            longitude = Decimal(str(longitude_str))
        except (InvalidOperation, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid coordinate format'})
        
        # Validate coordinate ranges
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            return JsonResponse({'success': False, 'error': 'Coordinates out of valid range'})
        
        # Get the current user (who is the customer)
        user = request.user
        
        # Create or update primary location
        location, created = CustomerLocation.objects.update_or_create(
            customer=user,
            is_primary=True,
            defaults={
                'latitude': latitude,
                'longitude': longitude,
                'address': address,
                'source': 'browser',
                'is_verified': False
            }
        )
        
        # Update user's main location fields
        user.latitude = latitude
        user.longitude = longitude
        if address:
            user.address = address
        user.save()
        
        # Clear cache after saving location
        cache_key = f'customer_locations_{request.user.tenant.id}'
        cache.delete(cache_key)
        
        return JsonResponse({
            'success': True,
            'message': 'Location saved successfully',
            'location_id': location.id,
            'latitude': float(latitude),
            'longitude': float(longitude)
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_http_methods(['GET'])
def get_customer_locations(request):
    """Get customer locations for ISP map (AJAX) with caching"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    tenant = request.user.tenant
    
    # Create cache key
    cache_key = f'customer_locations_{tenant.id}'
    
    # Try to get from cache first
    cached_data = cache.get(cache_key)
    if cached_data:
        print(f"========== USING CACHED DATA ==========")
        return JsonResponse(cached_data)
    
    print(f"========== GENERATING FRESH DATA ==========")
    print(f"Request user: {request.user.username}")
    print(f"User role: {request.user.role}")
    print(f"Tenant: {tenant}")
    
    # Get customers with location data
    customers_with_location = CustomUser.objects.filter(
        tenant=tenant,
        role='customer'
    ).exclude(
        latitude__isnull=True,
        longitude__isnull=True
    ).select_related('tenant').prefetch_related('subscriptions')
    
    print(f"Customers with location data: {customers_with_location.count()}")
    
    locations = []
    
    # Import here to avoid circular imports
    from router_manager.models import Router, Device
    from billing.models import Subscription
    
    for user in customers_with_location:
        try:
            # Get active subscription
            subscription = Subscription.objects.filter(
                user=user,
                is_active=True,
                end_date__gte=timezone.now()
            ).first()
            
            # Determine pin color based on status
            pin_color = get_pin_color(user, subscription)
            
            # Get online status
            is_online = False
            online_devices = 0
            
            try:
                # Check router status
                user_router = Router.objects.filter(user=user).first()
                
                if user_router:
                    is_online = user_router.is_online
                    
                    # Count online devices as backup
                    if not is_online:
                        online_devices = Device.objects.filter(
                            router=user_router, 
                            is_online=True
                        ).count()
                        is_online = online_devices > 0
                
            except Exception as e:
                print(f"Error checking online status for {user.username}: {e}")
            
            # Prepare location data
            location_data = {
                'id': user.id,
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
                'email': user.email or f'{user.username}@example.com',
                'latitude': float(user.latitude) if user.latitude else 0,
                'longitude': float(user.longitude) if user.longitude else 0,
                'address': user.address or 'No address specified',
                'pin_color': pin_color,
                'is_online': is_online,
                'online_devices': online_devices,
                'is_active_customer': getattr(user, 'is_active_customer', False),
                'subscription': {
                    'has_subscription': bool(subscription),
                    'plan_name': subscription.plan.name if subscription and subscription.plan else 'No Plan',
                    'days_remaining': subscription.days_remaining if subscription else 0,
                    'is_active': subscription.is_active if subscription else False,
                    'start_date': subscription.start_date.isoformat() if subscription and subscription.start_date else None,
                    'end_date': subscription.end_date.isoformat() if subscription and subscription.end_date else None,
                } if subscription else {
                    'has_subscription': False,
                    'plan_name': 'No Plan',
                    'days_remaining': 0,
                    'is_active': False,
                    'start_date': None,
                    'end_date': None,
                },
                'router': {
                    'has_router': bool(user_router),
                    'is_online': user_router.is_online if user_router else False,
                    'model': user_router.model if user_router else None,
                } if user_router else {
                    'has_router': False,
                    'is_online': False,
                    'model': None,
                },
                'location_verified': getattr(user, 'location_verified', False),
                'phone': getattr(user, 'phone', ''),
                'last_login': user.last_login.isoformat() if user.last_login else None,
            }
            
            locations.append(location_data)
            
            print(f"Added customer {user.username}: "
                  f"lat={user.latitude}, "
                  f"lng={user.longitude}, "
                  f"color={pin_color}, "
                  f"active={getattr(user, 'is_active_customer', False)}, "
                  f"online={is_online}")
            
        except Exception as e:
            print(f"Error processing customer {user.id}: {e}")
            import traceback
            traceback.print_exc()
    
    # Get zones
    zones = ISPZone.objects.filter(tenant=tenant, is_active=True)
    zone_data = []
    
    for zone in zones:
        try:
            zone_data.append({
                'id': zone.id,
                'name': zone.name,
                'color': zone.color or '#3B82F6',
                'geojson': zone.geojson if zone.geojson else {},
                'bounds': {
                    'min_lat': float(zone.min_lat) if zone.min_lat else -1.5,
                    'max_lat': float(zone.max_lat) if zone.max_lat else -1.0,
                    'min_lng': float(zone.min_lng) if zone.min_lng else 36.5,
                    'max_lng': float(zone.max_lng) if zone.max_lng else 37.0,
                } if zone.min_lat else {
                    'min_lat': -1.5,
                    'max_lat': -1.0,
                    'min_lng': 36.5,
                    'max_lng': 37.0,
                },
                'customer_count': getattr(zone, 'customer_count', 0)
            })
            print(f"Added zone {zone.name}")
        except Exception as e:
            print(f"Error processing zone {zone.id}: {e}")
    
    # If no zones, add a default zone
    if not zone_data:
        zone_data.append({
            'id': 'default',
            'name': 'Default Zone',
            'color': '#3B82F6',
            'geojson': {},
            'bounds': {
                'min_lat': -1.5,
                'max_lat': -1.0,
                'min_lng': 36.5,
                'max_lng': 37.0,
            },
            'customer_count': len(locations)
        })
        print("Added default zone")
    
    response_data = {
        'success': True,
        'locations': locations,
        'zones': zone_data,
        'total': len(locations),
        'timestamp': timezone.now().isoformat(),
        'cache_key': cache_key,
    }
    
    # Cache the data for 5 minutes
    cache.set(cache_key, response_data, 300)  # 5 minutes cache
    
    print(f"========== RESPONSE DATA CACHED ==========")
    print(f"Returning {len(locations)} locations and {len(zone_data)} zones")
    print(f"Cached with key: {cache_key}")
    
    return JsonResponse(response_data, safe=False)


@login_required
def customer_details(request, customer_id):
    """View detailed customer information"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    # Get the customer user
    customer_user = get_object_or_404(CustomUser, id=customer_id, role='customer')
    
    # Get subscription info
    subscription = Subscription.objects.filter(
        user=customer_user,
        is_active=True
    ).first()
    
    # Get devices info
    devices = []
    online_devices = 0
    try:
        from router_manager.models import Device
        devices = Device.objects.filter(user=customer_user)
        online_devices = devices.filter(is_online=True).count()
    except ImportError:
        pass
    
    # Get location history
    locations = CustomerLocation.objects.filter(customer=customer_user).order_by('-is_primary', '-created_at')
    
    context = {
        'customer_user': customer_user,
        'customer': customer_user,  # For backward compatibility in templates
        'subscription': subscription,
        'devices': devices,
        'online_devices': online_devices,
        'locations': locations,
        'page_title': f'Customer Details - {customer_user.username}',
        'page_subtitle': 'View customer information and history',
    }
    
    return render(request, 'accounts/customer_details.html', context)


@login_required
@require_http_methods(['POST'])
def verify_customer_location(request, customer_id):
    """ISP admin verify a customer's location"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        data = json.loads(request.body)
        customer_user = get_object_or_404(CustomUser, id=customer_id, role='customer')
        
        # Verify the location
        customer_user.location_verified = True
        customer_user.location_verified_at = timezone.now()
        customer_user.location_verified_by = request.user
        
        # Also verify the primary CustomerLocation
        primary_location = CustomerLocation.objects.filter(
            customer=customer_user, 
            is_primary=True
        ).first()
        
        if primary_location:
            primary_location.is_verified = True
            primary_location.verified_at = timezone.now()
            primary_location.verified_by = request.user
            primary_location.save()
        
        customer_user.save()
        
        # Clear cache after verification
        cache_key = f'customer_locations_{customer_user.tenant.id}'
        cache.delete(cache_key)
        
        return JsonResponse({
            'success': True,
            'message': 'Location verified successfully',
            'verified_at': customer_user.location_verified_at.isoformat(),
            'verified_by': request.user.username
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_customer_location_history(request, customer_id):
    """Get location history for a customer"""
    if request.user.role not in ['isp_admin', 'isp_staff', 'customer']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    user = request.user
    
    # Customers can only see their own history
    if user.role == 'customer' and str(user.id) != customer_id:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        customer_user = CustomUser.objects.get(id=customer_id, role='customer')
        locations = CustomerLocation.objects.filter(customer=customer_user).order_by('-created_at')
        
        location_data = []
        for loc in locations:
            location_data.append({
                'id': loc.id,
                'latitude': float(loc.latitude) if loc.latitude else 0,
                'longitude': float(loc.longitude) if loc.longitude else 0,
                'address': loc.address,
                'city': loc.city,
                'country': loc.country,
                'source': loc.source,
                'is_primary': loc.is_primary,
                'is_verified': loc.is_verified,
                'created_at': loc.created_at.isoformat() if loc.created_at else None,
                'verified_at': loc.verified_at.isoformat() if loc.verified_at else None,
                'verified_by': loc.verified_by.username if loc.verified_by else None
            })
        
        return JsonResponse({
            'success': True,
            'customer_id': customer_user.id,
            'customer_name': customer_user.get_full_name(),
            'locations': location_data,
            'count': len(location_data)
        })
        
    except CustomUser.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Customer not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_http_methods(['POST'])
def bulk_update_customer_locations(request):
    """ISP admin bulk update customer locations (CSV import)"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    if request.method == 'POST' and request.FILES.get('csv_file'):
        try:
            tenant = request.user.tenant
            csv_file = request.FILES['csv_file']
            
            # Parse CSV
            import csv
            from io import TextIOWrapper
            
            decoded_file = TextIOWrapper(csv_file.file, encoding='utf-8')
            reader = csv.DictReader(decoded_file)
            
            required_fields = ['customer_id', 'latitude', 'longitude', 'address']
            
            results = {
                'success': 0,
                'failed': 0,
                'errors': []
            }
            
            for row in reader:
                try:
                    # Validate required fields
                    if not all(field in row for field in required_fields):
                        results['errors'].append(f"Row missing required fields: {row}")
                        results['failed'] += 1
                        continue
                    
                    customer_id = row['customer_id']
                    latitude = Decimal(row['latitude'])
                    longitude = Decimal(row['longitude'])
                    address = row['address']
                    
                    # Validate coordinates
                    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                        results['errors'].append(f"Invalid coordinates for customer {customer_id}")
                        results['failed'] += 1
                        continue
                    
                    # Get customer
                    customer_user = CustomUser.objects.get(
                        id=customer_id,
                        tenant=tenant,
                        role='customer'
                    )
                    
                    # Create or update primary location
                    location, created = CustomerLocation.objects.update_or_create(
                        customer=customer_user,
                        is_primary=True,
                        defaults={
                            'latitude': latitude,
                            'longitude': longitude,
                            'address': address,
                            'source': 'admin_import',
                            'is_verified': True,
                            'verified_by': request.user,
                            'verified_at': timezone.now()
                        }
                    )
                    
                    # Update customer's main location
                    customer_user.latitude = latitude
                    customer_user.longitude = longitude
                    customer_user.address = address
                    customer_user.location_verified = True
                    customer_user.location_verified_at = timezone.now()
                    customer_user.location_verified_by = request.user
                    customer_user.save()
                    
                    results['success'] += 1
                    
                except CustomUser.DoesNotExist:
                    results['errors'].append(f"Customer not found: {row.get('customer_id')}")
                    results['failed'] += 1
                except InvalidOperation:
                    results['errors'].append(f"Invalid coordinate format for customer {row.get('customer_id')}")
                    results['failed'] += 1
                except Exception as e:
                    results['errors'].append(f"Error processing row {row}: {str(e)}")
                    results['failed'] += 1
            
            # Clear cache after bulk update
            cache_key = f'customer_locations_{tenant.id}'
            cache.delete(cache_key)
            
            return JsonResponse({
                'success': True,
                'message': f'Processed {results["success"]} locations successfully, {results["failed"]} failed',
                'results': results
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'No CSV file provided'})


@login_required
def assign_customer_to_zone(request, customer_id, zone_id):
    """Assign customer to a specific zone"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        tenant = request.user.tenant
        customer_user = get_object_or_404(CustomUser, id=customer_id, tenant=tenant, role='customer')
        zone = get_object_or_404(ISPZone, id=zone_id, tenant=tenant)
        
        # Check if customer has location
        if not customer_user.has_location:
            return JsonResponse({'success': False, 'error': 'Customer has no location set'})
        
        # Verify customer is within zone boundaries
        if (zone.min_lat <= customer_user.latitude <= zone.max_lat and 
            zone.min_lng <= customer_user.longitude <= zone.max_lng):
            
            # You might want to add a field to track zone assignment
            # For now, we'll just return success
            zone.update_customer_count()  # Update zone statistics
            
            return JsonResponse({
                'success': True,
                'message': f'Customer {customer_user.username} assigned to zone {zone.name}',
                'zone_name': zone.name
            })
        else:
            return JsonResponse({
                'success': False, 
                'error': f'Customer location is outside zone {zone.name} boundaries'
            })
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_customer_location_status(request, customer_id):
    """Get customer location status summary"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        customer_user = get_object_or_404(CustomUser, id=customer_id, role='customer')
        
        location_data = {
            'has_location': customer_user.has_location,
            'latitude': float(customer_user.latitude) if customer_user.latitude else None,
            'longitude': float(customer_user.longitude) if customer_user.longitude else None,
            'address': customer_user.address,
            'location_verified': customer_user.location_verified,
            'location_verified_at': customer_user.location_verified_at.isoformat() if customer_user.location_verified_at else None,
            'location_verified_by': customer_user.location_verified_by.username if customer_user.location_verified_by else None,
            'location_status': customer_user.location_status,
        }
        
        # Get location history count
        location_count = CustomerLocation.objects.filter(customer=customer_user).count()
        
        return JsonResponse({
            'success': True,
            'customer_id': customer_user.id,
            'customer_name': customer_user.get_full_name(),
            'location_data': location_data,
            'location_count': location_count
        })
        
    except CustomUser.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Customer not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
def search_address(request):
    """Proxy endpoint for OpenStreetMap Nominatim API"""
    if request.method == 'GET':
        query = request.GET.get('q', '')
        limit = request.GET.get('limit', '5')
        countrycodes = request.GET.get('countrycodes', 'ke')
        
        if not query:
            return JsonResponse({'error': 'Query parameter "q" is required'}, status=400)
        
        # Construct Nominatim URL
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': query,
            'format': 'json',
            'limit': limit,
            'countrycodes': countrycodes,
            'bounded': 1,
        }
        
        # Add headers to identify your application
        headers = {
            'User-Agent': 'M-Neti/1.0 (admin@mneti.com)',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Transform the data if needed
            results = []
            for item in data:
                results.append({
                    'display_name': item.get('display_name', ''),
                    'lat': item.get('lat', ''),
                    'lon': item.get('lon', ''),
                    'type': item.get('type', ''),
                    'address': item.get('address', {}),
                })
            
            return JsonResponse({'results': results})
            
        except requests.exceptions.RequestException as e:
            logger.error(f"OSM API error: {e}")
            return JsonResponse({'error': 'Failed to fetch location data'}, status=500)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return JsonResponse({'error': 'Internal server error'}, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def reverse_geocode(request):
    """Convert coordinates to address"""
    if request.method == 'GET':
        lat = request.GET.get('lat')
        lon = request.GET.get('lon')
        
        if not lat or not lon:
            return JsonResponse({'error': 'Latitude and longitude required'}, status=400)
        
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            'lat': lat,
            'lon': lon,
            'format': 'json',
        }
        
        headers = {
            'User-Agent': 'M-Neti/1.0 (admin@mneti.com)',
        }
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response.json()
            return JsonResponse(data)
        except Exception as e:
            logger.error(f"Reverse geocode error: {e}")
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

# OPTION 4: Cached geocoding view
@method_decorator(csrf_exempt, name='dispatch')
class GeocodeView(View):
    """Handle geocoding with caching and rate limiting"""
    
    def get_cache_key(self, params):
        """Generate cache key from parameters"""
        param_str = json.dumps(params, sort_keys=True)
        return f'geocode_{hashlib.md5(param_str.encode()).hexdigest()}'
    
    def get(self, request):
        query = request.GET.get('q', '')
        limit = request.GET.get('limit', '5')
        countrycodes = request.GET.get('countrycodes', 'ke')
        
        if not query:
            return JsonResponse({'error': 'Query required'}, status=400)
        
        # Check cache first
        params = {'q': query, 'limit': limit, 'countrycodes': countrycodes}
        cache_key = self.get_cache_key(params)
        cached_data = cache.get(cache_key)
        
        if cached_data:
            logger.info(f"Cache hit for: {query}")
            return JsonResponse(cached_data)
        
        # Make API call
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': query,
            'format': 'json',
            'limit': limit,
            'countrycodes': countrycodes,
            'bounded': 1,
        }
        
        headers = {
            'User-Agent': 'M-Neti/1.0 (contact@mneti.com)',
        }
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = {'results': response.json()}
            
            # Cache for 1 hour (OSM requests should be cached)
            cache.set(cache_key, data, 3600)
            
            return JsonResponse(data)
            
        except requests.exceptions.Timeout:
            logger.error("OSM API timeout")
            return JsonResponse({'error': 'Service timeout'}, status=504)
        except requests.exceptions.HTTPError as e:
            logger.error(f"OSM API HTTP error: {e}")
            return JsonResponse({'error': 'Geocoding service error'}, status=502)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return JsonResponse({'error': 'Internal error'}, status=500)

# Mapbox geocoding alternative (if you want to use Mapbox)
@csrf_exempt
def mapbox_geocode(request):
    """Use Mapbox Geocoding API (requires API token)"""
    if request.method == 'GET':
        query = request.GET.get('q', '')
        limit = request.GET.get('limit', '5')
        
        if not query:
            return JsonResponse({'error': 'Query required'}, status=400)
        
        # Get Mapbox token from settings (you need to add this to your settings.py)
        from django.conf import settings
        access_token = getattr(settings, 'MAPBOX_ACCESS_TOKEN', '')
        
        if not access_token:
            return JsonResponse({'error': 'Mapbox access token not configured'}, status=500)
        
        url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"
        params = {
            'access_token': access_token,
            'limit': limit,
            'country': 'ke',  # Kenya
            'types': 'address,place,neighborhood,locality',
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Transform Mapbox response to match our format
            results = []
            for feature in data.get('features', []):
                results.append({
                    'display_name': feature.get('place_name', ''),
                    'lat': feature['center'][1] if 'center' in feature else '',
                    'lon': feature['center'][0] if 'center' in feature else '',
                    'type': feature.get('place_type', [''])[0],
                    'address': {
                        'name': feature.get('text', ''),
                        'region': feature.get('context', [{}])[0].get('text', '') if feature.get('context') else '',
                        'country': 'Kenya'
                    }
                })
            
            return JsonResponse({'results': results})
            
        except Exception as e:
            logger.error(f"Mapbox geocoding error: {e}")
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

# ==================== END GEOCODING FUNCTIONS ====================