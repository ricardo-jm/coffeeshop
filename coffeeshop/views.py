from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, \
    permission_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse
from django.http import Http404
from django.core.mail import send_mail
from csp.decorators import csp_update
import django.middleware.csrf
from rest_framework import viewsets
from rest_framework import permissions
import django.contrib.auth.views
from datetime import datetime
from django.db import connection
import pathlib
import os
import json
import xml.etree.ElementTree as ET
import logging
import re

import coffeeshopsite.settings
from .models import *
from .forms import *
from .serializers import *
from .permissions import *

from django.utils.html import escape #escape to sanitize user input

##########################################################
# Helpers


def get_cart_size(user):
    cart_size = 0
    if (user is not None and user.is_authenticated):
        if (user.cart_set.count() > 0):
            cart = user.cart_set.first()
            cart_size = cart.cartitem_set.count()
    return cart_size

############################################################
# Pages


def index(request):
    products = Product.objects.all().order_by('name')
    cart_size = get_cart_size(request.user)

    context = {"products": products, "cart_size": cart_size}
    return render(request, 'coffeeshop/index.html', context)


def product(request, id):
    try:
        product = Product.objects.get(pk=id)
    except Exception as e:
        raise Http404
    cart_size = get_cart_size(request.user)
    comments = Comment.objects.filter(product_id=id)
    context = {"product": product, "cart_size": cart_size,
               'comments': comments}
    return render(request, 'coffeeshop/product.html', context)

# Don't use a function like this in real applications.  It is vulnerable
# to XSS attacks.  It's only purpose here is to demonstrate the vulnerability.
def vuln_product(request):
    if ('id' not in request.GET):
        context = {"error_msg": 'No product id given'}
        return render(request, 'coffeeshop/error.html', context)
    else:
        id = request.GET['id']
        try:
            product = Product.objects.get(pk=id)
        except Exception as e:
            print(request.GET['id'], 'XXX', str(id))
            context = {"error_msg": 'Product ' + str(id) + ' not found.'}
            return render(request, 'coffeeshop/error.html', context)

    cart_size = get_cart_size(request.user)
    comments = Comment.objects.filter(product_id=id)
    context = {"product": product, "cart_size": cart_size,
               'comments': comments}
    return render(request, 'coffeeshop/product.html', context)


def myaccount(request):
    cart_size = get_cart_size(request.user)

    context = {"cart_size": cart_size}
    return render(request, 'coffeeshop/myaccount.html', context)


@login_required
def basket(request):
    cart = None
    cart_size = 0
    if (request.user.cart_set.count() > 0):
        cart = request.user.cart_set.first()
        cart_size = cart.cartitem_set.count()

    address = None
    address_count = request.user.address_set.count()
    if (address_count > 0):
        address = request.user.address_set.first()

    card = None
    card_count = request.user.card_set.count()
    if (card_count > 0):
        card = request.user.card_set.first()
    context = {"cart": cart, "cart_size": cart_size,
               "address": address, "card": card}

    return render(request, 'coffeeshop/basket.html', context)


@login_required
def orders(request):
    orders = Order.objects.filter(user_id=request.user.id)
    cart_size = get_cart_size(request.user)

    context = {"orders": orders, "cart_size": cart_size}

    return render(request, 'coffeeshop/orders.html', context)


@login_required
@require_http_methods(["POST"])
def addtocart(request):
    log = logging.getLogger('django')
    error_msg = ""
    product_id = None
    product = None
    cart_size = 0
    if ('id' not in request.POST):
        error_msg = "Product not found"
    else:
        try:
            product_id = int(request.POST['id'])
            product = Product.objects.get(id=product_id)
        except Exception as e:
            log.error(e)
            error_msg = "Product not found"
    quantity = 1
    if ('qty' in request.POST):
        try:
            quantity = int(request.POST['qty'])
            if (quantity < 1):
                error_msg = "Invalid quantity"
        except Exception as e:
            log.error(e)
            error_msg = "Invalid quantity"
    if (error_msg == ""):
        try:
            cart = None
            if (request.user.cart_set.count() > 0):
                cart = request.user.cart_set.first()
                cart_size = cart.cartitem_set.count()
            else:
                cart = Cart(user_id=request.user.id)
                cart.save()
            cart_item = None
            for item in cart.cartitem_set.all():
                if (item.product_id == product_id):
                    cart_item = item
                    break
            cart_size = cart.cartitem_set.count()
            if (cart_item is None):
                cart_item = CartItem(product_id=product_id, cart_id=cart.id,
                                     quantity=quantity)
                cart_size += 1
            else:
                cart_item.quantity += quantity
            cart_item.save()
        except Exception as e:
            log.error(e)
            error_msg = "Can't add item to cart"

    if (error_msg == ""):
        context = {"cart_size": cart_size}
        return render(request, 'coffeeshop/itemadded.html', context)
    else:
        context = {"cart_size": cart_size, 'error_msg': error_msg}
        return render(request, 'coffeeshop/error.html', context)


@login_required
@require_http_methods(["POST"])
def updatecart(request):
    log = logging.getLogger('django')
    error_msg = ""
    product_id = None
    product = None
    cart_size = 0
    if ('id' not in request.POST):
        error_msg = "Product not found"
    else:
        try:
            product_id = int(request.POST['id'])
            product = Product.objects.get(id=product_id)
        except Exception as e:
            log.error(e)
            error_msg = "Product not found"
    quantity = 1
    if ('qty' in request.POST):

        try:
            quantity = int(request.POST['qty'])
            if (quantity < 0):
                error_msg = "Invalid quantity"
        except Exception as e:
            log.error(e)
            error_msg = "Invalid quantity"
    if (error_msg == ""):
        try:
            cart = None
            if (request.user.cart_set.count() > 0):
                cart = request.user.cart_set.first()
                cart_size = cart.cartitem_set.count()
            else:
                error_msg = "Cart is empty"
        except Exception as e:
            log.error(e)
            error_msg = "Couldn't fetch cart"

    if (error_msg == ""):
        cart_item = None
        try:
            cart_items = cart.cartitem_set.filter(product_id=product_id)
            if (cart_items.count() == 0):
                error_msg = "Item not found in cart"
            else:
                cart_item = cart_items.first()
        except Exception as e:
            log.error(e)
            error_msg = "Item not found in cart"

    if (error_msg == ""):
        if (quantity == 0):
            cart_item.delete()
        else:
            cart_item.quantity = quantity
            cart_item.save()

    if (error_msg == ""):
        context = {"cart_size": cart_size}
        return redirect(reverse('basket'))
    else:
        context = {'cart_size': cart_size, 'error_msg': error_msg}
        return render(request, 'coffeeshop/error.html', context)


@login_required
@require_http_methods(["POST"])
def placeorder(request):
    log = logging.getLogger('django')
    error_msg = ""
    cart_size = 0
    try:
        cart = None
        if (request.user.cart_set.count() > 0):
            cart = request.user.cart_set.first()
            cart_size = cart.cartitem_set.count()
        else:
            error_msg = "Cart is empty"
    except Exception as e:
        log.error(e)
        error_msg = "Couldn't fetch cart"
    if (error_msg == ""):
        order = Order(user_id=request.user.id, order_date=datetime.now())
        order.save()
        for cartitem in cart.cartitem_set.all():
            orderitem = OrderItem(order_id=order.id,
                                  product_id=cartitem.product.id,
                                  quantity=cartitem.quantity)
            orderitem.save()
            order.orderitem_set.add(orderitem)
        cart.delete()
        cart_size = 0
        context = {"cart_size": cart_size, "order_id": order.id}
        return render(request, 'coffeeshop/orderplaced.html', context)
    else:
        context = {'cart_size': cart_size, 'error_msg': error_msg}
        return render(request, 'coffeeshop/error.html', context)


# This is a very bad mail implementation.  Not only does it not have
# error checking and input sanitisation but it has a command
# injection vulnerability.
# Do not use in real applications
@login_required
@require_http_methods(["GET", "POST"])
def contact(request):
    log = logging.getLogger('django')
    cart_size = get_cart_size(request.user)
    error_msg = ''
    context = {'cart_size': cart_size}
    if request.method == 'GET':
        return render(request, 'coffeeshop/contact.html', context)

    if ('message' not in request.POST or len(request.POST['message']) == 0):
        error_msg = 'No message given.'
    if (error_msg == ''):
        # Vulnerable OS command injection
		#body = request.POST['message']
        #cmd = ' printf "From: ' + request.user.email + \
        #    '\nSubject: CoffeeShop User Contact\n\n' + body + \
        #    '" | ssmtp contact@coffeeshop.com'
			
        body = re.sub(r'[^\w\s.,!?]', '', request.POST['message'])
        cmd = f"From: {request.user.email}\nSubject: CoffeeShop User Contact\n\n{body}"
        log.info("Command: " + cmd)
        os.system(cmd)
        context = {'cart_size': cart_size}
        return render(request, 'coffeeshop/emailsent.html', context)

    context = {'cart_size': cart_size, 'error_msg': error_msg}
    return render(request, 'coffeeshop/error.html', context)


# This is a very bad search form.  It's only purpose is to illustrate
# SQL injection vulnerabilities.
# Don't use it in real applications
@require_http_methods(["POST"])
#@csrf_exempt
def search(request):
    log = logging.getLogger('django')

    cart_size = get_cart_size(request.user)
    search_term = None
    if ('search' in request.POST):
        search_text = request.POST['search']

    if (search_text is not None and search_text != ''):
        with connection.cursor() as cursor:
            sql = '''SELECT id, name, description, unit_price
					 FROM coffeeshop_product 
					 WHERE LOWER(name) LIKE %s OR LOWER(description) LIKE %s''' 
            print(sql)
			
            products = []
            try:
                cursor.execute(sql)
                for row in cursor.fetchall():
                    (pk, name, description, unit_price) = row
                    product = Product(id=pk, name=name,
                                      description=description,
                                      unit_price=unit_price)
                    products.append(product)
            except Exception as e:
                log.error("Error in search: " + sql)

    context = {"products": products, "cart_size": cart_size,
               "header": 'Search'}
    return render(request, 'coffeeshop/index.html', context)


@login_required
@require_http_methods(["POST"])
def addcomment(request):
        form = AddCommentForm(request.POST)
        if (form.is_valid()):
            comment_text = form.cleaned_data['comment']
            product_id = escape(form.cleaned_data['product_id'])
            comment = Comment(author_id=request.user.id,
                              product_id=product_id,
                              datetime=datetime.now(),
                              comment=comment_text)
            comment.save()
            next_url = "/product/" + str(product_id)
            return redirect(next_url)
        return HttpResponse(status=401)


@login_required
@require_http_methods(["POST"])
def delcomment(request):
    log = logging.getLogger('django')

    form = DelCommentForm(request.POST)
    if (form.is_valid()):
        id = form.cleaned_data['id']
    else:
        raise Http404
    try:
        comment = Comment.objects.get(pk=id)
        product_id = comment.product_id
        next_url = "/product/" + str(product_id)
    except Exception as e:
        log.error(e)
        raise Http404
    if (comment.author == request.user):
        comment.delete()
    else:
        raise Http404
    return redirect(next_url)


@login_required
@require_http_methods(["GET", "POST"])
#@csrf_exempt  # this is a bad idea - it is to demonstrate a vulnerability only
def changeemail(request):
    log = logging.getLogger('django')
    cart_size = get_cart_size(request.user)
    if (request.method == "GET"):
        context = {"cart_size": cart_size}
        return render(request, 'coffeeshop/changeemail.html', context)

    error_msg = ""
    form = ChangeEmailForm(request.POST)
    if (form.is_valid()):
        old_email = form.cleaned_data['old_email']
        new_email = form.cleaned_data['new_email']
        confirm_email = form.cleaned_data['confirm_email']
        log.info("Email:", old_email, new_email, confirm_email)
        if (new_email != confirm_email):
            error_msg = "New emails do not match"
        elif (old_email != request.user.email):
            error_msg = "Old email is not correct"
    else:
        error_msg = "Inputs were not valid"

    if (error_msg == ""):
        try:
            request.user.email = new_email
            request.user.save()
        except Exception as e:
            log.error(e)
            raise Http404

    if (error_msg == ""):
        context = {"cart_size": cart_size}
        return render(request, 'coffeeshop/emailchanged.html', context)
    else:
        context = {"cart_size": cart_size, 'error_msg': error_msg}
        return render(request, 'coffeeshop/error.html', context)


# Returns the CSRF token as a JSON string
@require_http_methods(["GET", "HEAD"])
#@csrf_exempt
def getcsrftoken(request):
    return JsonResponse({'csrftoken':
                         django.middleware.csrf.get_token(request)})


# Tests the CSRF token is correct
@require_http_methods(["POST"])
def testcsrftoken(request):
    csrftoken = request.POST['csrfmiddlewaretoken']
    return JsonResponse({'status': 'ok',
                         'received': csrftoken,
                         'correct': django.middleware.csrf.get_token(request)})


# CSP report handler - send as email
#@csrf_exempt
def email_csp_report(request):
    log = logging.getLogger('django')
    json_str = request.body
    log.info("CSP report " + str(json_str))
    if (isinstance(json_str, bytes)):
        json_str = json_str.decode(request.encoding or 'utf-8')
    report = json.dumps(json.loads(json_str), indent=4, sort_keys=True,
                        separators=(',', ':'))
    send_mail(
        'CSP Exception',
        report,
        'security@coffeeshop.com',
        ['ops@coffeeshop.com'],
        fail_silently=False,
    )
    return HttpResponse('')


# This is a badly-written API call to retrieve the stock
# level.
# Its purpose is to demonsrate the Billion Laughs vulnerability.
# Don't use it as a template for productive code - it contains
# other vulnerabilities besides Billion Laughs
@require_http_methods(["POST"])
#@csrf_exempt
def stocklevel(request):
    root = ET.fromstring(request.body)
    if (root.tag != 'product'):
        raise Http500
    try:
        product_id = int(root.text)
        quantity = \
            StockLevel.objects.get(product_id=product_id).quantity_available
    except:
        raise Http500
    return JsonResponse({'quantity': quantity})


##############################################################
# Other views for practising techniques on

# Simply throws an exception, for practising error handling
def pagewitherror(request):
    product = Product.objects.get(pk=100)


# Presents a page with two XMLHttpRequest (actually jquery .ajax()) requests
# for practising CORS headers
def corstest(request):
    context = {}
    return render(request, 'coffeeshop/corstest.html', context)


# Presents a page with two XMLHttpRequest (actually jquery .ajax()) requests
# for practising CORS headers
def gallery(request):
    context = {}
    return render(request, 'coffeeshop/gallery.html', context)

###################################################################
# REST API


# View set demonstrating good REST practice
class AddressViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)

    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated, OwnsAddress]

    def perform_create(self, serializer):
        return serializer.save(user=self.request.user)


def download_file(request):
    file_name = request.GET.get('file', '')
    base_directory = '/vagrant/coffeeshopsite/coffeeshop/files/'
    
    # Insecure file path construction
    #file_path = os.path.join(base_directory, file_name)

    #Secure file path construction

    file_path = os.path.normpath(os.path.join(base_directory, file_name))

    if file_path.startswith(base_directory):
        try:
            with open(file_path, 'rb') as f:
                response = HttpResponse(f.read(), content_type='application/octet-stream')
                response['Content-Disposition'] = f'attachment; filename="{file_name}"'
                return response
        except FileNotFoundError:
            return HttpResponse("File not found")
    else: 
        return HttpResponse(file_path)