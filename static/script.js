document.addEventListener('DOMContentLoaded', () => {
    const itemShopBtn = document.getElementById('itemShopBtn');
    const ogBtn = document.getElementById('ogBtn');
    const shopImage = document.getElementById('shopImage');
    const hash = window.shopHash; // Retrieve the hash from the global variable

    function loadImage(src) {
        const img = new Image();
        img.onload = () => {
            shopImage.src = src;
            shopImage.style.opacity = 1;
        };
        img.src = src;
    }

    itemShopBtn.addEventListener('click', () => {
        if (!itemShopBtn.classList.contains('active')) {
            itemShopBtn.classList.add('active');
            ogBtn.classList.remove('active');
            shopImage.style.opacity = 0;
            setTimeout(() => {
                loadImage(`/shops/shop-${hash}.jpg`);
            }, 300);
        }
    });

    ogBtn.addEventListener('click', () => {
        if (!ogBtn.classList.contains('active')) {
            ogBtn.classList.add('active');
            itemShopBtn.classList.remove('active');
            shopImage.style.opacity = 0;
            setTimeout(() => {
                loadImage(`/shops/og/og-${hash}.jpg`);
            }, 300);
        }
    });

    // Modal functionality
    const imageModal = document.getElementById('imageModal');
    const modalImage = document.getElementById('modalImage');
    const closeModal = document.getElementById('closeModal');

    shopImage.addEventListener('click', () => {
        modalImage.src = shopImage.src;
        imageModal.style.display = 'block';
    });

    closeModal.addEventListener('click', () => {
        imageModal.style.display = 'none';
    });

    // Close modal when clicking outside the image
    imageModal.addEventListener('click', (event) => {
        if (event.target === imageModal) {
            imageModal.style.display = 'none';
        }
    });
});
